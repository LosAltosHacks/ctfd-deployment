

if (typeof loadchals !== 'undefined') {
    var stock_loadchals = loadchals
    loadchals = function(cb) {
        stock_loadchals(function() {
            // Color the challenges
            $.get(script_root + "/api/v1/lah_challenges", function (response) {
                info = response.data;

                $("button.challenge-button").not(".solved-challenge").each(function(index) {
                    id = Number.parseInt(this.value)
                    if (!info.unlocked[id]) {
                        $(this).css("background-color", "#a32727");
                        $(this).css("opacity", "0.8");
                        $(this).css("border", "none")
                    }
                    if (info.selected === id) {
                        $(this).css("background-color", "#d66436");
                        $(this).css("opacity", "0.7");
                        $(this).css("border", "none")
                    }
                })

                if (cb) {
                    cb();
                }
            })
        });
    }
}
