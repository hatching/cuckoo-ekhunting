import $ from 'jquery';
import Templates from './templates';

const urls = {
  add: () => '/group/add',
  add_url: () => '/group/add/url',
  view: (id, d = 0) => `/group/view/${id}?details=${d}`,
  view_urls: (group_id, l = 1000, o = 0) => `/group/view/${group_id}?limit=${l}&offset=${o}`,
  delete: () => '/group/delete',
  delete_url: () => '/group/delete/url'
}

// displays an error in the form above the input
function handleError(message = 'Something went wrong', $form) {

  if($form) {

    // generate error html
    let el = $(Templates.ajaxError({
      message,
      span: $form ? $form.find('thead th').length : '100%'
    }));

    // only display one row at once
    if($form.find('.error-row').length)
      $form.find('.error-row').remove();

    // inject error row
    $form.find('.input-row').before(el);

    // make the row user-dismissable
    el.find('button[data-dismiss]').on('click', e => {
      el.remove();
      return false;
    });
  }

}

// POST's a new group to the api
function addGroup(d = {}) {

  // construct data payload to server
  let data = Object.assign({
    name: '',
    description: ''
  }, d);

  // resolve the request as a promise
  return new Promise((resolve, reject) => $.post(urls.add(), data, response => {

    if(response.group_id)
      data.id = response.group_id;

    resolve({
      data,
      html: Templates.urlGroup(data),
      jq: function() { return $(this.html); }
    });

  }).fail(err => reject(err)));

}

// called on appending
function rowHandler($el = null, $form) {
  if(!$el) {
    // init specific new element
  } else {
    // just handle a form init
  }
}

function initUrlGroups($form) {

  // pre-init available rows
  rowHandler(null, $form);

  return new Promise((resolve, reject) => {

    // default form submission handler
    $form.on('submit', e => {

      e.preventDefault();

      // find the values for adding groups
      let name = $form.find('#group-name').val();
      let description = $form.find('#group-description').val();

      // /groups/add request to server
      addGroup({name, description}).then(response => {

        // update UI with things
        let el = response.jq();
        $form.find('table > tbody > .input-row').after(response.jq());
        rowHandler(el, null);
        $form.find('#group-name, #group-description').val('');
        $form.find('#group-name').focus(); // autofocus name field again

      }).catch(e => {

        // catch up on errors (renders error-row in table with message)
        if(e.responseJSON instanceof Object) {
          handleError(e.responseJSON.message || null, $form);
        } else {
          handleError(null, $form);
        }
      });
    });

    resolve();
  });
}

export { initUrlGroups }
