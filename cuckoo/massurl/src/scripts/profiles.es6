import $ from 'jquery';

/*
  Creates a promise mapping of the API calls
  usage:

  api.call(name, data, id)
  api.call('get', {}, 1)
 */
const api = {
  get: (d,id) => $.get(`/api/profile/${id}`),
  list: (d,id) => $.get(`/api/profile/list`),
  add: (d,id) => $.post(`/api/profile/add`, d),
  update: (d,id) => $.post(`/api/profile/update/${id}`, d),
  delete: (d,id) => $.post(`/api/profile/delete/${id}`),
  call: function(name=false, id=null, data={}) {
    return new Promise((res,rej) => {
      if(this.hasOwnProperty(name)) {
        this[name](data,id).done(response => {
          res(response);
        }).fail(err => rej(err));
      } else {
        rej(`${name} is not a registered API call`);
      }
    });
  }
};

function initProfiles() {
  return new Promise((resolve, reject) => {

    // api.call('add', null, {
    //   name: 'First profile',
    //   browser: 'ie',
    //   route: 'internet',
    // }).then(response => {
    //
    // }).catch(err => console.log(err));

    api.call('list').then(response => console.log(response));

    // api.call('get', 1).then(response => console.log(response));

    // api.call('update', 1, {
    //   name: 'First profile updated',
    //   browser: 'ff',
    //   route: 'internet',
    // }).then(r => console.log(r));

    // api.call('delete', 1).then(response => console.log(response));

  });
}

export { initProfiles };
