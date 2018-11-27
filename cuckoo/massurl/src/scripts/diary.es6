import $ from 'jquery';

const APIUrl = (endpoint=false) => `/api/diary/${endpoint ? endpoint : '/'}`;

const api = {
  get: id => APIUrl(id)
};

// loads a diary from the api
function loadDiary(id) {
  return new Promise((resolve, reject) => {
    $.get(api.get(id), res => resolve(res), err => reject(err), "json");
  });
}

// populates a diary
function populateDiary(data={}) {
  return new Promise((resolve, reject) => {
    resolve();
  });
}

// initializes the diary
function initDiary(el, id) {
  return new Promise((resolve, reject) => {
    loadDiary(parseInt(id)).then(data => {
      populateDiary().then()
      resolve();
    });
  });
}

export { initDiary };
