from __future__ import division  # Use floating point for math calculations
from CTFd.plugins.challenges import BaseChallenge, CHALLENGE_CLASSES
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.flags import get_flag_class
from CTFd.models import db, Solves, Fails, Flags, Challenges, ChallengeFiles, Tags, Teams, Hints, Users
from CTFd import utils
from CTFd.utils.migrations import upgrade
from CTFd.utils.user import get_ip
from CTFd.utils.uploads import upload_file, delete_file
from CTFd.utils.modes import get_model
from flask import Blueprint

from CTFd.utils.dates import ctftime
from sqlalchemy import func
import logging
import datetime
import time
from random import randrange
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from CTFd.utils.decorators import (
    during_ctf_time_only,
    require_verified_emails,
    admins_only,
    authed_only
)

class LahChallengeClass(BaseChallenge):
    id = "lah"  # Unique identifier used to register challenges
    name = "lah unlocking"  # Name of a challenge type
    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/lah_challenges/assets/create.html',
        'update': '/plugins/lah_challenges/assets/update.html',
        'view': '/plugins/lah_challenges/assets/view.html',
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/lah_challenges/assets/create.js',
        'update': '/plugins/lah_challenges/assets/update.js',
        'view': '/plugins/lah_challenges/assets/view.js',
    }
    # Route at which files are accessible. This must be registered using register_plugin_assets_directory()
    route = '/plugins/lah_challenges/assets/'
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint('lah_challenges', __name__, template_folder='templates', static_folder='assets')

    @staticmethod
    def create(request):
        """
        This method is used to process the challenge creation request.

        :param request:
        :return:
        """
        data = request.form or request.get_json()
        challenge = LahChallenge(**data)

        db.session.add(challenge)
        db.session.commit()

        return challenge

    @staticmethod
    def read(challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.

        :param challenge:
        :return: Challenge object, data dictionary to be returned to the user
        """
        challenge = LahChallenge.query.filter_by(id=challenge.id).first()
        data = {
            'id': challenge.id,
            'name': challenge.name,
            'value': challenge.value,
            'unlock_order': challenge.unlock_order,
            'is_unlocked': challenge.is_unlocked,
            'description': challenge.description,
            'category': challenge.category,
            'state': challenge.state,
            'max_attempts': challenge.max_attempts,
            'type': challenge.type,
            'type_data': {
                'id': LahChallengeClass.id,
                'name': LahChallengeClass.name,
                'templates': LahChallengeClass.templates,
                'scripts': LahChallengeClass.scripts,
            }
        }
        return data

    @staticmethod
    def update(challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.

        :param challenge:
        :param request:
        :return:
        """
        data = request.form or request.get_json()
        do_lock = challenge.unlock_order == 0 and int(data['unlock_order']) > 0
        for attr, value in data.items():
            setattr(challenge, attr, value)

        if do_lock:
            challenge.is_unlocked = False
        # for some reason challenge.unlock_order doesn't work here
        if int(data['unlock_order']) <= 0:
            challenge.is_unlocked = True
        db.session.commit()
        return challenge

    @staticmethod
    def delete(challenge):
        """
        This method is used to delete the resources used by a challenge.

        :param challenge:
        :return:
        """
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            delete_file(f.id)
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        LahChallenge.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()

    @staticmethod
    def attempt(challenge, request):
        """
        This method is used to check whether a given input is right or wrong. It does not make any changes and should
        return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
        user's input from the request itself.

        :param challenge: The Challenge object from the database
        :param request: The request the user submitted
        :return: (boolean, string)
        """
        chal = LahChallenge.query.filter_by(id=challenge.id).first()
        if not chal.is_unlocked:
            return False, 'Not unlocked yet'
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        flags = Flags.query.filter_by(challenge_id=challenge.id).all()
        for flag in flags:
            if get_flag_class(flag.type).compare(flag, submission):
                return True, 'Correct'
        return False, 'Incorrect'

    @staticmethod
    def solve(user, team, challenge, request):
        """
        This method is used to insert Solves into the database in order to mark a challenge as solved.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        chal = LahChallenge.query.filter_by(id=challenge.id).first()
        if not chal.is_unlocked:
            raise RuntimeError("Attempted to solve a locked lah challenge.")

        # check if this is the selected solve
        unlock = get_unlock_state()
        if unlock.selected == challenge.id:
            with db.session.no_autoflush:
                unlock.selected = None
                unlock.unlocker_id = user.id
                unlock.expiration = datetime.datetime.now() + datetime.timedelta(minutes = 1)
            scheduler.add_job(unlock_timeout_callback, DateTrigger(unlock.expiration), id=UNLOCK_TIMEOUT_JOB_ID, replace_existing=True, misfire_grace_time=999999999)
            db.session.commit()

        data = request.form or request.get_json()
        submission = data['submission'].strip()
        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(req=request),
            provided=submission
        )
        db.session.add(solve)
        db.session.commit()
        db.session.close()

    @staticmethod
    def fail(user, team, challenge, request):
        """
        This method is used to insert Fails into the database in order to mark an answer incorrect.

        :param team: The Team object from the database
        :param challenge: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        wrong = Fails(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(request),
            provided=submission
        )
        db.session.add(wrong)
        db.session.commit()
        db.session.close()


class LahChallenge(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'lah'}
    id = db.Column(None, db.ForeignKey('challenges.id'), primary_key=True)
    unlock_order = db.Column(db.Integer, default=99)
    is_unlocked = db.Column(db.Boolean, default=False)

    def __init__(self, *args, **kwargs):
        super(LahChallenge, self).__init__(**kwargs)
        self.is_unlocked = int(kwargs['unlock_order']) == 0


# TODO implement a config for this
RAND_UNLOCK_MINUTES = list(range(0, 60, 15))
RAND_UNLOCK_QUESTIONS = 1

def log(logger, format, **kwargs):
    logger = logging.getLogger(logger)
    props = {
        'date': time.strftime("%m/%d/%Y %X"),
    }
    props.update(kwargs)
    msg = format.format(**props)
    print(msg)
    logger.info(msg)

APP_REF = None

def rand_unlock_callback():
    with APP_REF.app_context():
        if not ctftime():
            log('lah', "[{date}] unlocking did not run because ctf has not started")
            return
        if datetime.datetime.utcnow().minute not in RAND_UNLOCK_MINUTES:
            log('lah', "[{date}] unlocking did not run because minute is not aligned")
            return
        for i in range(RAND_UNLOCK_QUESTIONS):
            # Unlock one random question, that is visible, not unlocked, and of the lowest available unlock_order
            min_order = db.session.query(
                            func.min(LahChallenge.unlock_order).label("min_order"),
                            func.count().label("count")
                        ).filter(
                            LahChallenge.state == "visible",
                            LahChallenge.is_unlocked == False,
                            LahChallenge.unlock_order > 0,
                        ).one()
            count = min_order.count
            order = min_order.min_order
            if not min_order or count == 0:
                log('lah', "[{date}] unlocking finished early because no locked challenges were found.")
                return
            rand_offset = randrange(count)
            challenge = LahChallenge.query.filter_by(unlock_order=order, is_unlocked=False, state="visible").order_by(LahChallenge.id).offset(rand_offset).first()
            if not challenge:
                log('lah', "[{date}] encountered invalid state: randomly selected challenge was None.")
            challenge.is_unlocked = True
            db.session.commit()
            log('lah', "[{date}] unlocked challenge '{chal}'", chal=challenge.name)

UNLOCK_TIMEOUT_JOB_ID = 'time_out_job_id'
RAND_UNLOCK_JOB_ID = 'rand_unlock_job_id'

scheduler = BackgroundScheduler()
scheduler.add_jobstore(SQLAlchemyJobStore(engine=db.engine))
scheduler.add_job(func=rand_unlock_callback, trigger="interval", minutes=1, id=RAND_UNLOCK_JOB_ID, replace_existing=True)


from flask import (
    current_app as app,
    render_template,
    request,
    redirect,
    url_for,
    Blueprint,
    abort,
    render_template_string,
    send_file
)

from CTFd.utils.user import get_current_user


class UnlockState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    selected = db.Column(db.Integer, db.ForeignKey('lah_challenge.id'), nullable=True, default=None)
    unlocker_id = db.Column(None, db.ForeignKey('users.id'), nullable=True, default=1)
    expiration = db.Column(db.DateTime, nullable=True, default=datetime.datetime.fromtimestamp(13569465600))

    __table_args__ = (
        db.CheckConstraint('(selected IS NULL) <> (unlocker_id IS NULL)'),
        db.CheckConstraint('(expiration IS NULL) = (unlocker_id IS NULL)'),
    )

def get_unlock_state():
    unlock = UnlockState.query.one_or_none()
    if unlock:
        return unlock
    db.session.add(UnlockState(id=1))
    db.session.commit()
    return get_unlock_state()

def unlock_timeout_callback():
    with APP_REF.app_context():
        count = db.session.query(LahChallenge).filter(
                        LahChallenge.state == "visible",
                        LahChallenge.is_unlocked == False
                    ).count()
        if count == 0:
            log('lah', "[{date}] manual unlock timeout finished early because no locked challenges were found.")
            return
        rand_offset = randrange(count)
        challenge = LahChallenge.query.filter_by(is_unlocked=False, state="visible").order_by(LahChallenge.id).offset(rand_offset).first()
        if not challenge:
            log('lah', "[{date}] encountered invalid state during manual unlock timeout: randomly selected challenge was None.")
            return
        challenge.is_unlocked = True
        unlock = get_unlock_state()
        with db.session.no_autoflush:
            unlock.unlocker_id = None
            unlock.expiration = None
            unlock.selected = challenge.id
        db.session.commit()
        log('lah', "[{date}] unlocked challenge '{chal}' on timeout", chal=challenge.name)

from CTFd.plugins import bypass_csrf_protection, register_user_page_menu_bar, register_plugin_script

lah_print = Blueprint('lah_challenges', __name__, template_folder='templates', static_folder='assets', url_prefix="")

@lah_print.route('/unlock', methods=['GET', 'POST'])
@bypass_csrf_protection
@authed_only
def lah_unlock():
    if request.method == 'POST':
        unlock = get_unlock_state()
        if get_current_user().id != unlock.unlocker_id:
            abort(403)
        challenge = LahChallenge.query.filter_by(id=request.form['unlock']).one_or_none()
        if not challenge:
            return redirect(url_for('lah_challenges.lah_unlock'))
        challenge.is_unlocked = True
        unlock.unlocker_id = None
        unlock.expiration = None
        unlock.selected = challenge.id
        db.session.commit()
        try:
            scheduler.remove_job(UNLOCK_TIMEOUT_JOB_ID)
        except JobLookupError:
            pass
        return redirect(url_for('challenges.listing'))
    unlockables = dict(LahChallenge.query.filter_by(is_unlocked=False, state="visible").with_entities(LahChallenge.id, LahChallenge.name).all())
    unlock = get_unlock_state()
    if unlock.unlocker_id:
        waiting = "user '" + db.session.query(Users.name).filter(Users.id==unlock.unlocker_id).scalar() + "'"
    else:
        waiting = "challenge '" + db.session.query(LahChallenge.name).filter(LahChallenge.id==unlock.selected).scalar() + "'"
    if unlock.expiration:
        cdown = unlock.expiration.timestamp()
    else:
        cdown = None
    return render_template('unlock.html',
        challenges=unlockables,
        countdown_end=cdown,
        waiting=waiting,
        unlocker_id=unlock.unlocker_id,
        user_id=get_current_user().id,
    )

@lah_print.route('/admin/unlock_reset', methods=['GET'])
@bypass_csrf_protection
@admins_only
@authed_only
def unlock_reset():
    unlock = get_unlock_state()
    with db.session.no_autoflush:
        unlock.selected = None
        unlock.unlocker_id = get_current_user().id
        unlock.expiration = datetime.datetime.now() + datetime.timedelta(seconds = 30)
    print(unlock.expiration)
    scheduler.add_job(unlock_timeout_callback, DateTrigger(unlock.expiration), id=UNLOCK_TIMEOUT_JOB_ID, replace_existing=True, misfire_grace_time=99999999)
    db.session.commit()
    return redirect(url_for('lah_challenges.lah_unlock'))

## API for redirects and color

from flask_restplus import Resource, Namespace
from CTFd.utils.decorators import (
    during_ctf_time_only,
    require_verified_emails,
)
from CTFd.utils.decorators.visibility import (
    check_challenge_visibility,
)

lah_challenges_namespace = Namespace('lah_challenges',
                                 description="Endpoint to get info specific to lah challenges")

@lah_challenges_namespace.route('')
class LahChallengeInfo(Resource):
    @check_challenge_visibility
    @during_ctf_time_only
    @require_verified_emails
    def get(self):
        response = {}
        challenges = LahChallenge.query.filter_by(state="visible").all()

        response['unlocked'] = {}
        for challenge in challenges:
            response['unlocked'][challenge.id] = challenge.is_unlocked

        unlock = get_unlock_state()
        response['selected'] = unlock.selected
        db.session.close()
        return {
            'success': True,
            'data': response
        }

from CTFd.api import CTFd_API_v1
CTFd_API_v1.add_namespace(lah_challenges_namespace, '/lah_challenges')

def load(app):
    # upgrade()
    app.db.create_all()
    CHALLENGE_CLASSES['lah'] = LahChallengeClass
    register_plugin_assets_directory(app, base_path='/plugins/lah_challenges/assets/')
    global APP_REF
    APP_REF = app
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())

    app.register_blueprint(lah_print)
    register_user_page_menu_bar("Unlocking", "/unlock")
    register_plugin_script("/plugins/lah_challenges/assets/lah_challenge_injector.js")
