import $ from './jquery-with-plugins';
import Handlebars from 'handlebars';

const api = {
  list: () => $.get('/api/signatures/list'),
  get: id => $.get(`/api/signature/${id}`),
  create: data => $.jpost('/api/signature/add', data),
  update: (id,data) => $.jpost(`/api/signature/update/${id}`, data),
  delete: id => $.post(`/api/signature/delete/${id}`, data),
  run: id => $.post(`/api/signature/run/${id}`, data)
};

const $SIG_FORM = (data={}) => Handlebars.compile(`

`)(data);

function loadSignatures() {
  return new Promise((res, rej) => api.list().done(sigs => res(sigs)).fail(err => rej(err)));
}

function createSignature(data={}) {
  return new Promise((res, rej) => {
    let body = {
      name: null,
      content: [],
      enabled: false,
      level: 1,
      ...data
    };
    // validation can be done here
    api.create(body).done(response => res(response)).fail(err => rej(err));
  });
}

function updateSignature(id, data) {
  return new Promise((res, rej) => {
    res();
  });
}

function deleteSignature() {
  return new Promise((res, rej) => {
    res();
  });
}

function initSignatures($el) {
  return new Promise((resolve, reject) => {
    resolve();
  });
}

export { initSignatures };
