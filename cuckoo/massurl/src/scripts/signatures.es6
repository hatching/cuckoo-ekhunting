import $ from './jquery-with-plugins';

const api = {
  get: () => {},
  post: () => {},
  update: () => {},
  delete: () => {}
};

function loadSignatures() {
  return new Promise((res, rej) => {
    res();
  });
}

function createSignature() {
  return new Promise((res, rej) => {
    res();
  });
}

function updateSignature() {
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
    console.log('init signatures on ', $el);
    resolve();
  });
}

export { initSignatures };
