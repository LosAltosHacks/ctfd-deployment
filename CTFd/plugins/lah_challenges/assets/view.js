window.challenge.data = undefined;

window.challenge.renderer = new markdownit({
    html: true,
});

window.challenge.preRender = function () {

};

window.challenge.render = function (markdown) {
    return window.challenge.renderer.render(markdown);
};


window.challenge.postRender = function () {

};


window.challenge.submit = function (cb, preview) {
    var challenge_id = parseInt($('#challenge-id').val());
    var submission = $('#submission-input').val();
    var url = "/api/v1/challenges/attempt";

    if (preview) {
        url += "?preview=true";
    }

    var params = {
        'challenge_id': challenge_id,
        'submission': submission
    };

    var wasCorrect = false;
    var willRedirect = false;
    CTFd.fetch("/api/v1/lah_challenges", {
        method: 'GET',
        credentials: 'same-origin',
        headers: {
            'Accept': 'application/json',
        }
    }).then(function (response) {
        return response.json()
    }).then(function (response) {
        if (response && response.data.selected == challenge_id) {
            willRedirect = true
        }
    }).then(function() {
        return CTFd.fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
    }).then(function (response) {
        if (response.status === 429) {
            // User was ratelimited but process response
            return response.json();
        }
        if (response.status === 403) {
            // User is not logged in or CTF is paused.
            return response.json();
        }
        return response.json();
    }).then(function (response) {
        wasCorrect = response.data.status == "correct"
        cb(response);
    }).then(function () {
        if (wasCorrect && willRedirect) {
            setTimeout(function() {
                $(location).attr('href', '/unlock')
            }, 700)
        }
    });
};
