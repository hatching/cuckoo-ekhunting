import $ from 'jquery';
import Templates from './templates';

const APIUrl = (endpoint=false) => `/api/group/${endpoint ? endpoint : '/'}`;

const urls = {
  add: () => APIUrl(`add`),
  add_url: () => APIUrl('add/url'),
  view: (id, d = 0) => APIUrl(`view/${id}?details=${d}`),
  delete: () => APIUrl('delete')
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

// deletes a group
function deleteGroup(group_id = undefined) {
  return new Promise((resolve, reject) => {
    let youSure = confirm('Delete this group?');
    if(!group_id)
      return reject('No id located');
    if(youSure) {
      $.post(urls.delete(), {group_id:parseInt(group_id)}, response => {
        resolve(response);
      }).fail(e => reject(e));
    } else {
      reject(false);
    }
  });
}

// called on appending
function rowHandler($el = null, $form) {

  // per-row handler
  let row = $e => {
    let edButton = $e.find('button[data-edit]');
    let rmButton = $e.find('button[data-remove]');

    rmButton.on('click', e => {
      let id = $e.attr('data-group-id');
      if(id) {
        deleteGroup(id).then(response => {
          $e.remove();
          resolve(response);
        }).catch(e => {
          if(e !== false && e.responseJSON) {
            handleError(e.responseJSON["message"] || null, $form);
          }
        });
      } else {
        handleError('Delete: could not locate id in row, aborting.', $form);
      }
    });

    // redirects to the url-groups page with the target id as a param
    edButton.on('click', e => {
      let id = $(e.currentTarget).parents('tr').data('groupId');
      if(id)
        window.location = `${window.location.origin}/url-groups/manage?mng=${id}`;
    });

  }

  if($el) {
    // init specific new element
    row($el);
  } else {
    // just handle a form init
    $form.find('tr:not(.input-row)').each((i, e) => {
      row($(e));
    });
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
        $form.find('table > tbody > .input-row').after(el);
        rowHandler(el, $form);
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

export {
  initUrlGroups
}
