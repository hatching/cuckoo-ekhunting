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

// POST's a new group to the api
function addGroup(d = {}) {

  let data = Object.assign({
    name: '',
    description: ''
  }, d);

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
      let name = $form.find('#group-name').val();
      let description = $form.find('#group-description').val();
      addGroup({name, description}).then(response => {

        let el = response.jq();
        $form.find('table > tbody > .input-row').after(response.jq());
        rowHandler(el, null);
        $form.find('#group-name, #group-description').val('');
        $form.find('#group-name').focus(); // autofocus name field again

      }).catch(e => console.error(e));
    });

    resolve();
  });
}

export { initUrlGroups }
