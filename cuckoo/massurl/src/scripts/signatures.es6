import moment from 'moment';
import $ from './jquery-with-plugins';
import Handlebars from 'handlebars';
import Prompt from './prompt';

const prompt = new Prompt();

Handlebars.registerHelper('eq', (p,m,opts) => p == m ? opts.fn() : '');
Handlebars.registerHelper('keys', (o,opts) => {
  let r = "";
  Object.keys(o).forEach(k => r += opts.fn(k));
  return r;
});
Handlebars.registerHelper('is-selected', (o,t) => {
  if(Object.keys(o)[0] == t) {
    return 'selected';
  } else {
    return '';
  }
});
Handlebars.registerHelper('pretty-date', timestamp => moment(timestamp).format('MM/DD/YYYY HH:mm:ss'));

// signature list item template
const $SIG_LIST_ITEM = (data={}) => Handlebars.compile(`
  <li data-filter-value="{{name}}">
     <a href="load:{{id}}">{{name}}</a>
   </li>
`)(data);

const $SIG_INPUT_ROW = (data={}) => Handlebars.compile(`
  {{#each this}}
    <div class="multi-input-row" data-sig-fields>
      <div class="multi-input-row__select">
        <div class="configure-block__control--wrapper mini caret">
          <select class="configure-block__control">
            <option value="any" {{is-selected this 'any'}}>Any</option>
            <option value="must" {{is-selected this 'must'}}>Must</option>
          </select>
        </div>
      </div>
      <div class="multi-input-row__fields">
        {{#each this}}
          {{#each this}}
              <input type="text" class="configure-block__control inline mini" value="{{this}}" />
            {{else}}
              <input type="text" class="configure-block__control inline mini" />
          {{/each}}
          {{else}}
            <input type="text" class="configure-block__control inline mini" />
        {{/each}}
      </div>
      <div class="multi-input-row__actions">
        <a href="#" data-remove-row title="Remove row"><i class="fas fa-times"></i></a>
      </div>
    </div>
  {{/each}}
`)(data);

// initialise helper for existing signature rows inside a template.
// initializing has to be done in inputRow()
Handlebars.registerHelper('input-row', (sig,opts) => {
  return new Handlebars.SafeString($SIG_INPUT_ROW(sig));
});

const $SIG_MATCHES = (data={}) => Handlebars.compile(`
  <h2><small>Displaying matches for</small>{{signature.name}}</h2>
  <div class="flex-v">
    <div class="full-block flex-v no-padding">
      <ul class="configure-content__list">
        {{#each matches}}
            <li>
              <a href="/diary/{{id}}">
                <p>{{url}}</p>
                <span>
                  <time datetime="{{timestamp}}">{{pretty-date timestamp}}</time>
                  <span>No. {{version}}</span>
                </span>
              </a>
            </li>
          {{else}}
            <li class="no-results">There are no matches related to this signature.</li>
        {{/each}}
      </ul>
    </div>
  </div>
`)(data);

// signature form template
const $SIG_FORM = (data={}) => Handlebars.compile(`

  <h2>{{signature.name}}
    {{#unless meta.new}}
      <a data-run-signature href="#" class="button">Find all matches</a>
    {{/unless}}
  </h2>
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
  <div class="flex-v">
    <div class="configure-block free">
      <h4 class="configure-block__label">Content</h4>
      <p class="configure-block__description">Create signatures. Assign an operator (any or must), followed by strings that should match the signature. Click 'add row' to add many lines.</p>
      <p class="configure-block__hotkeys">
        controls:
        <span>&#9166; add string</span>
        <span>&#9003; delete string</span>
      </p>
    </div>
    <div class="full-block tabbed">
      <ul class="tabbed-nav">
        {{#each signature.content}}
          <li><a {{#eq @index 0}}class="active"{{/eq}} href="tab:{{@key}}">{{@key}}</a></li>
        {{/each}}
      </ul>
      <div class="tabbed-content">
        {{#each signature.content}}
          <div class="tabbed-tab {{#eq @index 0}}active{{/eq}}" data-tab="{{@key}}">
            {{input-row this}}
            <div class="multi-input-row">
              <a href="#" data-create-row>Add row</a>
            </div>
          </div>
        {{/each}}
      </div>
    </div>
  </div>
  <footer {{#if meta.new}}class="align-right"{{/if}}>
    {{#unless meta.new}}
      <button id="delete-signature">Delete</button>
    {{/unless}}
    <button id="save-signature">{{#if meta.new}}Create{{else}}Save{{/if}}</button>
  </footer>

`)(data);

const state = {
  formParent: null,
  sigList: null,
  signature: null
}

const api = {
  list: () => $.get('/api/signatures/list'),
  get: id => $.get(`/api/signature/${id}`),
  create: data => $.jpost('/api/signature/add', data),
  update: (id,data) => $.jpost(`/api/signature/update/${id}`, data),
  delete: id => $.post(`/api/signature/delete/${id}`),
  run: (id,o=false,l=50) => {
    let url = `/api/signature/run/${id}?limit=${l}`;
    if(o)
      url += `&offset=${o}`;
    return $.post(url);
  }
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

function deleteSignature(id) {
  return new Promise((res, rej) => {
    api.delete(id).done(response => res(response)).fail(err => rej(err));
  });
};

function runSignature(id) {
  return new Promise((res, rej) => {
    api.run(id,0,30).done(response => res(response)).fail(err => rej(err));
  });
}

function displayMessage(message, type='info') {
  let template = $(Handlebars.compile(`
    <div class="message-box {{type}}">
      <p>
        {{#eq type "info"}}<i class="far fa-info-square"></i>{{/eq}}
        {{#eq type "success"}}<i class="far fa-check"></i>{{/eq}}
        {{message}}
        <a href="#" class="close"><i class="far fa-times"></i></a>
      </p>
    </div>
  `)({message,type}));
  return {
    render: function(parent,method='prepend') {
      if(parent.find('.message-box')) parent.find('.message-box').remove();
      parent[method](template);
      template.find('.close').on('click', e => template.remove());
    }
  }
}

// input row handlers
function inputRow(row) {

  let createInput = () => $(Handlebars.compile(`<input type="text" class="configure-block__control inline mini" />`)({}));

  let keyupHandler = e => {
    let target = e.currentTarget;
    switch(e.keyCode) {
      case 13:
        if(target.value.length) {
          if($(target).next().prop("tagName") == "INPUT") {
            // focus next input if next element is an input
            $(target).next().focus();
          } else {
            // else, create another input
            let inp = createInput();
            $(target).after(inp);
            inp.on('keyup', keyupHandler);
            inp.focus();
          }
        }
      break;
      case 8:
        if(target.value.length == 0) {
          if($(target).prev().prop('tagName') == 'INPUT') {
            $(target).prev().focus();
          } else if ($(target).next().prop('tagName') == 'INPUT') {
            $(target).next().focus();
          }
          if($(target).prev().length !== 0)
            $(target).remove();
        }
      break;
    }
  }

  // removes a row
  let removeRowHandler = e => {
    e.preventDefault();
    $(e.currentTarget).parents('.multi-input-row').remove();
  }

  $(row).find('input[type="text"]').on('keyup', keyupHandler);
  $(row).find('[data-remove-row]').on('click', removeRowHandler);
}

function getSignatureValues() {
  let { formParent } = state;
  let ret = {};
  formParent.find('.tabbed-tab').each((i,tab) => {
    let $tab = $(tab);
    ret[$tab.data('tab')] = [];
    $tab.find('[data-sig-fields]').each((i,fields) => {
      let entry = {};
      let type = $(fields).find('select').val()
      entry[type] = [];
      $(fields).find('input[type="text"]').each((i,inp) => {
        if(inp.value.length > 0)
          entry[type].push(inp.value);
      });
      ret[$tab.data('tab')].push(entry);
    });
  });
  return ret;
}

function displayMatchesList(matches=[]) {
  let { formParent } = state;
  let list = $($SIG_MATCHES({
    signature: state.signature,
    matches: matches
  }));
  formParent.html(list);

  let matchState = {
    limit: 30,
    offset: null,
    loading: false,
    end: false
  }

  if(matches.length) {
    matchState.offset = matches[matches.length-1].datetime;
  }

  // implement lazyload
  let scrollTainer = list.find('.configure-content__list');
  scrollTainer.on('scroll', e => {
    if(scrollTainer.scrollTop() + $(window).height() > scrollTainer[0].scrollHeight) {
      if(!matchState.loading && !matchState.end) {
        matchState.loading = true;
        api.run(state.signature.id, matchState.offset, matchState.limit).done(response => {
          response.forEach(m => {
            list.find('.configure-content__list').append(Handlebars.compile(`
              <li>
                <a href="/diary/{{id}}">
                  <p>{{url}}</p>
                  <span>
                    <time datetime="{{datetime}}">{{pretty-date datetime}}</time>
                    <span>No. {{version}}</span>
                  </span>
                </a>
              </li>
            `)(m));
          });

          if(response.length) {
            matches.concat(response);
            matchState.offset = matches[matches.length-1].datetime;
          }

          matchState.loading = false;
          if(response.length < matchState.limit)
            matchState.end = true;
        });
      }
    }
  });
}

function renderForm(signature, meta={}) {

  let { formParent, sigList } = state;
  state.signature = signature;

  // makes sure there's always the same tabs
  let content_fields = ["requests","responsedata","requestdata","javascript"];
  for(let f in content_fields) {
    if(!signature.content.hasOwnProperty(content_fields[f])) {
      signature.content[content_fields[f]] = [];
    }
  }

  let html = $SIG_FORM({signature,meta});
  formParent.html(html);

  // store the required input fields into object to serialize later on
  const fields = {
    name: formParent.find('#signature-name'),
    enabled: formParent.find('#signature-enabled'),
    level: formParent.find('#signature-level')
  }

  // enabled/disabled will toggle 'level' input
  formParent.find("#signature-enabled").on('change', e => {
    formParent.find("#signature-level")
      .parents('.configure-block')
      .prop('hidden', !$(e.currentTarget).is(':checked'));
  });

  // save or update signature
  formParent.find('#save-signature').on('click', e => {
    e.preventDefault();
    let serializeValues = () => {
      return {
        name: fields.name.val(),
        enabled: fields.enabled.is(':checked'),
        level: parseInt(fields.level.val()),
        content: getSignatureValues()
      }
    }
    $(e.currentTarget).html('<i class="fas fa-spinner-third fa-spin"></i>');

    let values = serializeValues();

    if(meta.new) {
      // POST new signature
      if(!values.name) {
        displayMessage('Enter a name before saving.').render(formParent);
        $(e.currentTarget).text('Save');
        return;
      }
      createSignature(values).then(response => {
        let listItem = $($SIG_LIST_ITEM({id:response.signature_id,name:fields.name.val()}));
        state.sigList.append(listItem);
        listItem.find('a').on('click', sigClickHandler).click();
        setTimeout(() => $(e.currentTarget).text('Save'), 500);
      }).catch(err => {
        displayMessage(err.responseJSON.message).render(formParent);
      });
    } else {
      // UPDATE signature
      delete values.name;
      updateSignature(signature.id, values).then(response => {
        setTimeout(() => $(e.currentTarget).text('Save'), 500);
      }).catch(err => displayMessage(err.responseJSON.message).render(formParent));
    }
  });

  // delete signature
  formParent.find('#delete-signature').on('click', e => {

    $(e.currentTarget).blur();

    prompt.ask({
      title: 'Deleting signature',
      description: 'This action cannot be undone. Proceed?',
      confirmText: 'Delete',
      dismissText: 'Keep',
      icon: 'trash-alt'
    }).then(() => {
      $(e.currentTarget).html('<i class="fas fa-spinner-third fa-spin"></i>');
      deleteSignature(signature.id).then(response => {
        sigList.find(`a[href="load:${signature.id}"]`).parents('li').remove();
        formParent.empty();
      }).catch(err => displayMessage(err.responseJSON.message).render(formParent));
    });

  });

  // initialize sig tabs
  formParent.find('.tabbed-nav a').on('click', e => {
    e.preventDefault();
    let target = $(e.currentTarget).attr('href').split(':')[1];
    $(e.currentTarget).parents('ul').find('a').removeClass('active');
    $(e.currentTarget).addClass('active');
    $(e.currentTarget).parents('.tabbed').find('[data-tab]').removeClass('active');
    $(e.currentTarget).parents('.tabbed').find(`[data-tab='${target}']`).addClass('active');
  });

  // initialize signature editor rows - new
  formParent.find('.tabbed-tab [data-create-row]').on('click', e => {
    e.preventDefault();
    let $row = $($SIG_INPUT_ROW({
      any: []
    }));
    $(e.currentTarget).parent().before($row);
    inputRow($row);
  });

  // initialize signature editor rows - existing
  formParent.find('.tabbed-tab .multi-input-row').each((i,el) => inputRow(el));

  // handler for running a signature
  formParent.find('[data-run-signature]').on('click', e => {
    runSignature(signature.id).then(response => {
      // here needs to come an action after running the signature.
      displayMatchesList(response);
    }).catch(err => displayMessage(err.responseJSON.message).render(formParent));
  });

};

let sigClickHandler = e => {
  e.preventDefault();
  let link = $(e.currentTarget);
  let id = link.attr('href').split(':')[1];
  link.prepend(`<i class="fas fa-spinner-third fa-spin"></i>`);
  loadSignature(id).then(sig => {
    setTimeout(() => {
      link.find('i').remove();
      link.parents('ul').find('.active').removeClass('active');
      link.addClass('active');
      renderForm(sig,{new:false});
    }, 500);
  }).catch(err => displayMessage(err.responseJSON.message).render($el));
};

function initSignatures($el) {

  state.formParent = $("[data-signatures-form]");
  state.sigList = $("[data-signatures-list]");

  return new Promise((resolve, reject) => {

    // create new signature button - populates form
    $("#create-new-signature").on('click', e => {
      state.signature = null;
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
    }).catch(err => displayMessage(err.responseJSON.message).render($el));

    $el.find('input[name="filter-signatures"]').on('keyup', e => {
      let val = $(e.currentTarget).val();
      $el.find('[data-signatures-list]').filterList(val);
    });

    resolve();
  });
};

export { initSignatures };
