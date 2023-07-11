var $input = $('<div class="modal-body"><input type="text" class="form-control" placeholder="Message"></div>')

$(document).on('click', '.js-msgGroup', function () {
  $('.js-msgGroup, .js-newMsg').addClass('hide')
  $('.js-conversation').removeClass('hide')
  $('.modal-title').html('<a href="#" class="js-gotoMsgs">Back</a>')
  $input.insertBefore('.js-modalBody')
})

$(document).on('click', '.js-gotoMsgs', function () {
  $input.remove()
  $('.js-conversation').addClass('hide')
  $('.js-msgGroup, .js-newMsg').removeClass('hide')
  $('.modal-title').html('Messages')
})

$(document).on('click', '[data-action=growl]', function (e) {
  e.preventDefault()

  $('#app-growl').append(
    '<div class="alert alert-dark alert-dismissible fade in" role="alert">'+
      '<button type="button" class="close" data-dismiss="alert" aria-label="Close">'+
        '<span aria-hidden="true">×</span>'+
      '</button>'+
      '<p>Click the x on the upper right to dismiss this little thing. Or click growl again to show more growls.</p>'+
    '</div>'
  )
})

$(document).on('focus', '[data-action="grow"]', function () {
  if ($(window).width() > 1000) {
    $(this).animate({
      width: 300
    })
  }
})

$(document).on('blur', '[data-action="grow"]', function () {
  if ($(window).width() > 1000) {
    var $this = $(this).animate({
      width: 180
    })
  }
})

// back to top button - docs
$(function () {
  if ($('.docs-top').length) {
    _backToTopButton()
    $(window).on('scroll', _backToTopButton)
    function _backToTopButton () {
      if ($(window).scrollTop() > $(window).height()) {
        $('.docs-top').fadeIn()
      } else {
        $('.docs-top').fadeOut()
      }
    }
  }
})

$(function () {
    // doc nav js
    var $toc    = $('#markdown-toc')
    var $window = $(window)

    if ($toc[0]) {

      maybeActivateDocNavigation()
      $window.on('resize', maybeActivateDocNavigation)

      function maybeActivateDocNavigation () {
        if ($window.width() > 768) {
          activateDocNavigation()
        } else {
          deactivateDocNavigation()
        }
      }

      function deactivateDocNavigation() {
        $window.off('resize.theme.nav')
        $window.off('scroll.theme.nav')
        $toc.css({
          position: '',
          left: '',
          top: ''
        })
      }

      function activateDocNavigation() {

        var cache = {}

        function updateCache() {
          cache.containerTop   = $('.docs-content').offset().top - 40
          cache.containerRight = $('.docs-content').offset().left + $('.docs-content').width() + 45
          measure()
        }

        function measure() {
          var scrollTop = $window.scrollTop()
          var distance =  Math.max(scrollTop - cache.containerTop, 0)

          if (!distance) {
            $($toc.find('li')[1]).addClass('active')
            return $toc.css({
              position: '',
              left: '',
              top: ''
            })
          }

          $toc.css({
            position: 'fixed',
            left: cache.containerRight,
            top: 40
          })
        }

        updateCache()

        $(window)
          .on('resize.theme.nav', updateCache)
          .on('scroll.theme.nav', measure)

        $('body').scrollspy({
          target: '#markdown-toc',
          selector: 'li > a'
        })

        setTimeout(function () {
          $('body').scrollspy('refresh')
        }, 1000)
      }
    }
})

$(document).on('submit', '.ajax-form', function (e) {
    e.preventDefault();
    let form = $(this),
        payload = form.serializeArray().reduce((acc, val) => {
            acc[val.name] = val.value;
            return acc;
        }, {});

    form
        .removeClass('ajax-success ajax-error')
        .find('[data-error-msg]')
        .attr('data-error-msg', null);

    $.ajax({
        url: form.attr('action'),
        data: payload,
        method: "POST",
        complete: function (xhr) {
            if (xhr.status == 500) {
                alert('An unexpected error occurred while loading the page. The LaunchBox team has been notified about the error and will be fixing it shortly.');
            }
            else {
                let json = null, success = null;
                try {
                    json = JSON.parse(xhr.responseText);
                }
                catch { }

                let handled = form.triggerHandler('ajax-complete', [xhr, json]);

                if (!handled) {
                    if (json) {
                        success = json.Success;
                        for (let fieldName in json.Errors) {
                            form.find(`[name="${fieldName}"]`).parent().attr('data-error-msg', json.Errors[fieldName]);
                        }
                    }
                    else {
                        success = xhr.status == 200;
                    }

                    form.toggleClass('ajax-success', success);
                    form.toggleClass('ajax-error', !success);

                    if (success) {
                        form[0].reset();
                    }
                }
            }
        }
    });
});