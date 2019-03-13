import $ from './jquery-with-plugins';
import Handlebars from 'handlebars';

const state = {
  formParent: null,
  sigList: null
}

Handlebars.registerHelper('eq', (p,m,opts) => p == m ? opts.fn() : '');

// signature list item template
const $SIG_LIST_ITEM = (data={}) => Handlebars.compile(`
  <li>
    <a href="load:{{id}}">{{name}}</a>
  </li>
`)(data);

// signature form template
const $SIG_FORM = (data={}) => Handlebars.compile(`

  <h2>{{signature.name}}</h2>

  <div class="configure-block__container">

    {{#if meta.new}}
      <div class="configure-block">
        <label for="signature-name" class="configure-block__label">Signature name</label>
        <p class="configure-block__description">A unique name for this signature</p>
        <input class="configure-block__control" id="signature-name" name="signature-name" placeholder="Type name" required />
      </div>
    {{/if}}

    <div class="configure-block">
        <h4 class="configure-block__label">Enabled</h4>
        <p class="configure-block__description">Match this signature</p>
        <div class="configure-block__control checkbox">
          <input type="checkbox" id="signature-enabled" {{#if signature.enabled}}checked{{/if}} />
          <label for="signature-enabled">Enable</label>
        </div>
    </div>

    <div class="configure-block" {{#unless signature.enabled}}hidden{{/unless}}>
      <label class="configure-block__label" for="signature-level">Alert level</label>
      <p class="configure-block__description">Match level target</p>
      <div class="configure-block__control--wrapper mini caret">
        <select class="configure-block__control" name="signature-level" id="signature-level">
          <option value="1" {{#eq signature.level 1}}selected{{/eq}}>1</option>
          <option value="2" {{#eq signature.level 2}}selected{{/eq}}>2</option>
          <option value="3" {{#eq signature.level 3}}selected{{/eq}}>3</option>
        </select>
      </div>
    </div>

  </div>

  <div class="flex-v"></div>

  <footer {{#if meta.new}}class="align-right"{{/if}}>
    {{#unless meta.new}}
      <button id="delete-signature">Delete</button>
    {{/unless}}
    <button id="save-signature">{{#if meta.new}}Create{{else}}Save{{/if}}</button>
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

function loadSignature(id=false) {
  return new Promise((res, rej) => {
    if(id) {
      api.get(id).done(sig => res(sig)).fail(err => rej(err));
    } else {
      api.list().done(sigs => res(sigs)).fail(err => rej(err));
    }
  });
};

function createSignature(data) {
  return new Promise((res, rej) => {
    // validation can be done here
    api.create(data).done(response => res(response)).fail(err => rej(err));
  });
};

function updateSignature(id, data) {
  return new Promise((res, rej) => {
    api.update(id,data).done(response => res(response)).fail(err => rej(err));
  });
};

function deleteSignature() {
  return new Promise((res, rej) => {
    res();
  });
};

function renderForm(signature, meta={}) {

  let parent = state.formParent;
  let html = $SIG_FORM({signature,meta});
  parent.html(html);

  // store the required input fields into object to serialize later on
  const fields = {
    name: parent.find('#signature-name'),
    enabled: parent.find('#signature-enabled'),
    level: parent.find('#signature-level')
  }

  // enabled/disabled will toggle 'level' input
  parent.find("#signature-enabled").on('change', e => {
    parent.find("#signature-level")
      .parents('.configure-block')
      .prop('hidden', !$(e.currentTarget).is(':checked'));
  });

  parent.find('#save-signature').on('click', e => {
    e.preventDefault();
    let serializeValues = () => {
      console.log(fields.enabled);
      return {
        name: fields.name.val(),
        enabled: fields.enabled.is(':checked'),
        level: parseInt(fields.level.val()),
        content: {
          requests: [],
          responsedata: [],
          requestdata: [],
          javascript: []
        }
      }
    }
    if(meta.new) {
      // POST new signature
      createSignature(serializeValues()).then(response => {
        let listItem = $($SIG_LIST_ITEM({id:response.signature_id,name:fields.name.val()}));
        state.sigList.append(listItem);
        listItem.find('a').on('click', sigClickHandler).click();
      }).catch(err => console.log(err));
    } else {
      // UPDATE signature
      let values = serializeValues();
      delete values.name;
      updateSignature(signature.id, values).then(response => {
        console.log(response);
      }).catch(err => console.log(err));
    }
  });

};

let sigClickHandler = e => {
  e.preventDefault();
  let link = $(e.currentTarget);
  let id = link.attr('href').split(':')[1];
  loadSignature(id).then(sig => {
    link.parents('ul').find('.active').removeClass('active');
    link.addClass('active');
    renderForm(sig,{new:false});
  }).catch(err => console.log(err));
};

function initSignatures($el) {

  state.formParent = $("[data-signatures-form]");
  state.sigList = $("[data-signatures-list]");

  return new Promise((resolve, reject) => {

    // create new signature button - populates form
    $("#create-new-signature").on('click', e => {
      renderForm({
        name: 'New signature',
        enabled: false,
        level: 1,
        content: {
          requests: [],
          responsedata: [],
          requestdata: [],
          javascript: []
        }
      }, { new: true });
      state.sigList.find('.active').removeClass('active');
    });

    // load signature - populates form with existing signatures
    loadSignature(false).then(signatures => {
      signatures.forEach(sig => {
        let listItem = $($SIG_LIST_ITEM(sig));
        state.sigList.append(listItem);
      });
      state.sigList.find('a').on('click', sigClickHandler);
    }).catch(err => console.log(err));

    resolve();
  });
};

export { initSignatures };
