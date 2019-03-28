import moment from 'moment';
import autosize from 'autosize';
import $ from './jquery-with-plugins';
import Templates from './templates';

const APIUrl = (endpoint=false) => `/api/diary/${endpoint ? endpoint : '/'}`;

const translations = {
  ioc: 'indicator of compromise'
};

const api = {
  get: id => APIUrl(id)
};

let generateList = (arr=[],key=false,listClass="data-list") => {
  let ul = $(`<ul class="${listClass}" />`);
  arr.forEach(item => {
    let li = $("<li />");
    li.data('item', item);
    if(key !== false) {
      if(key !== '*')
        item = item[key];
      else {
        item = Object.keys(item)
                  .map(k => {
                    return `<div class="key-value">
                      <p class="key">${translations[k] || k}</p><p class="value">${item[k]}</p>
                    </div>`;
                  }).join('');
      }
    }
    if(key == '*')
      li.html(item);
    else
      li.text(item);

    ul.append(li);
  });
  return ul;
}

// transforms li content into disabled text fields
let textareafy = ul => {

  ul.find('li').each((i, li) => {
    let content = $(li).html();
    let ta = $("<textarea disabled></textarea>");
    ta.val(content);
    // ta.attr('disabled', true);
    $(li).html(ta);
  });

  return {
    list: ul,
    // call this function on render of the areas
    // sel = ALL(<textarea>)
    render: sel => {
      let open = s => {
        s.style.height = '1px';
        s.style.height = `${(25+s.scrollHeight)}px`;
      }
      sel.each((i,s) => {

        let isDisabled = false;
        if(s.hasAttribute('disabled')) {
          isDisabled = true;
          s = s.parentNode;
        }

        s.addEventListener('click', e => {
          let t = isDisabled ? s.querySelector('textarea') : s;
          if(t.classList.contains('open')) {
            t.classList.remove('open');
            t.style.height = 'auto';
          } else {
            open(t);
            t.classList.add('open');
          }
        });
      });
    }
  };

}

// loads a diary from the api
function loadDiary(id) {
  return new Promise((resolve, reject) => {
    $.get(api.get(id), res => resolve(res), err => reject(err), "json");
  });
}

// populates a diary
function populateDiary(data={},el) {
  let setHolder = (label,value) => {
    let ph = el.find(`[data-placeholder=${label}]`);
    if(ph.length) {
      ph.text(value);
      ph.attr('title', value);
    }
  };
  return new Promise((resolve, reject) => {

    let { url, datetime, version, requested_urls, signatures, javascript } = data;

    let requestsContainer = el.find('#diary-requests');
    let signaturesContainer = el.find('#diary-signatures');
    let javascriptContainer = el.find('#diary-javascript');

    // fills up placeholders
    setHolder('url', url);
    setHolder('datetime', moment(datetime).format('LLL'));
    setHolder('version', version);

    let overlayHandler = (view,data) => {
      let dialog = $(view(data));
      $("body").append(dialog);
      dialog.find('textarea').each((i, ta) => autosize(ta));
      dialog.find('.close-dialog').on('click', e => {
        e.preventDefault();
        dialog.remove();
      });
      return dialog;
    }

    // creates data fields
    let requestsList = textareafy(generateList(requested_urls, "url"));
    let signaturesList = generateList(signatures, '*', "default-list");
    let javascriptList = textareafy(generateList(javascript));

    requestsContainer.append(requestsList.list);
    signaturesContainer.append(signaturesList);
    javascriptContainer.append(javascriptList.list);

    requestsList.render(requestsList.list.find('textarea'));
    javascriptList.render(javascriptList.list.find('textarea'));

    // create hooks for displaying request logs
    requestsList.list.find('li').each(function() {
      let req = $(this).data('item');
      let btn = $(`<button class="expand" data-request-log="${req.request_log}" title="Expand for more information"><i class='fal fa-expand-alt'></i></button>`);
      $(this).prepend(btn);

      btn.on('click', evt => {
        evt.preventDefault();
        evt.stopPropagation();
        $.get(`/api/requestlog/${req.request_log}`).done(response => {
          let dialog = overlayHandler(Templates.requestView, response);
          dialog.find('textarea').each((i, ta) => autosize(ta));
        }).fail(err => console.log(err));
      });
    });

    // apply collapse toggles to sig list
    signaturesList.find('li').each((i,item) => {
      let collapse = $("<div />", {
        class: 'collapse'
      });
      collapse.html(`<p>${signatures[i].signature} <i class='caret'></a></p>`);
      $(item).prepend(collapse);
      collapse.on('click', e => collapse.nextAll('.key-value').toggleClass('hidden'));
      collapse.click();
    });

    javascriptList.list.find('li').each(function() {
      let req = $(this).data('item');
      let area = $(this).find('textarea');
      let btn = $(`<button class="expand"><i class='fal fa-expand-alt'></i></button>`);
      $(this).prepend(btn);

      btn.on('click', evt => {
        evt.preventDefault();
        evt.stopPropagation();
        let dialog = overlayHandler(Templates.payloadView, {
          payload: $.beautify(area.val()) // to do this, or not to do this.
        });
      });

    });

    let togglePane = e => e.currentTarget.parentNode.classList.toggle('closed');

    requestsContainer.parent().find('header').on('click', togglePane);
    signaturesContainer.parent().find('header').on('click', togglePane);
    javascriptContainer.parent().find('header').on('click', togglePane);

    resolve();
  });
}

// initializes the diary
function initDiary(el, id) {
  return new Promise((resolve, reject) => {
    loadDiary(id).then(data => {
      populateDiary(data,el).then(() => {
        resolve();
      });
    });
  });
}

export { initDiary };
