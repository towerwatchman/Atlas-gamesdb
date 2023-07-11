$(window).scroll(function () {
    if ($(this).scrollTop() > 1) {
        $(".dmtop").css({ bottom: "40px" });
    } else {
        $(".dmtop").css({ bottom: "-100px" });
    }
});

$(".dmtop").click(function () {
    $("html, body").animate({ scrollTop: "0px" }, 800);
    return false;
});

$("#search").keypress(function (e) {
    if (e.which === 13) {
        window.location.href = "/games/results/" + encodeURI($(this).val());
        return false;
    }
});

$("#searchButton").click(function (e) {
    window.location.href = "/games/results/" + encodeURI($("#search").val());
    return false;
})