import $ from './jquery-with-plugins';
import Handlebars from 'handlebars';

const state = {
  formParent: null
}

Handlebars.registerHelper('eq', (p,m,opts) => p == m ? opts.fn() : '');

const $SIG_FORM = (data={}) => Handlebars.compile(`

  <h2>{{name}}</h2>

  <div class="configure-block__container">

    <div class="configure-block">
      <label for="signature-name" class="configure-block__label">Signature name</label>
      <p class="configure-block__description">A unique name for this signature</p>
      <input class="configure-block__control" id="signature-name" name="signature-name" placeholder="Type name" required />
    </div>

    <div class="configure-block">
        <h4 class="configure-block__label">Enable</h4>
        <p class="configure-block__description">Match this signature</p>
        <div class="configure-block__control checkbox">
          <input type="checkbox" id="signature-enable" />
          <label for="signature-enable">Enable</label>
        </div>
    </div>

    <div class="configure-block" {{#unless enabled}}hidden{{/unless}}>
      <label class="configure-block__label">Alert level</label>
      <p class="configure-block__description">Match level target</p>
      <div class="configure-block__control--wrapper mini caret">
        <select class="configure-block__control" name="signature-alert-level" id="signature-alert-level">
          <option value="1" {{#eq level 1}}selected{{/eq}}>1</option>
          <option value="2" {{#eq level 2}}selected{{/eq}}>2</option>
          <option value="3" {{#eq level 3}}selected{{/eq}}>3</option>
        </select>
      </div>
    </div>

  </div>

  <div class="flex-v"></div>

  <footer {{#if meta.new}}class="align-right"{{/if}}>
    {{#unless meta.new}}
      <button id="delete-profile">Delete</button>
    {{/unless}}
    <button id="save-profile">{{#if meta.new}}Create{{else}}Save{{/if}}</button>
  </footer>

`)(data);

const api = {
  list: () => $.get('/api/signatures/list'),
  get: id => $.get(`/api/signature/${id}`),
  create: data => $.jpost('/api/signature/add', data),
  update: (id,data) => $.jpost(`/api/signature/update/${id}`, data),
  delete: id => $.post(`/api/signature/delete/${id}`, data),
  run: id => $.post(`/api/signature/run/${id}`, data)
};

function loadSignatures() {
  return new Promise((res, rej) => api.list().done(sigs => res(sigs)).fail(err => rej(err)));
};

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
};

function updateSignature(id, data) {
  return new Promise((res, rej) => {
    res();
  });
};

function deleteSignature() {
  return new Promise((res, rej) => {
    res();
  });
};

function renderForm(sig) {

  let parent = state.formParent;
  let html = $SIG_FORM(sig);
  parent.html(html);

  // enabled/disabled will toggle 'level' input
  parent.find("#signature-enable").on('change', e => {
    parent.find("#signature-alert-level")
      .parents('.configure-block')
      .prop('hidden', !$(e.currentTarget).is(':checked'));
  });

  

};

let sigClickHandler = e => {

};

function initSignatures($el) {

  state.formParent = $("[data-signatures-form]");

  return new Promise((resolve, reject) => {

    // create new signature button - populates form
    $("#create-new-signature").on('click', e => {

      renderForm({
        name: 'New signature',
        enabled: false,
        level: 1,
        content: []
      });

    });

    // load signature - populates form with existing signature


    resolve();
  });
};

export { initSignatures };
