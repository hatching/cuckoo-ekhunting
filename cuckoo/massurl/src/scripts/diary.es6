import moment from 'moment';
import $ from 'jquery';

const APIUrl = (endpoint=false) => `/api/diary/${endpoint ? endpoint : '/'}`;

const api = {
  get: id => APIUrl(id)
};

let generateList = (arr=[],key=false,listClass="data-list") => {
  let ul = $(`<ul class="${listClass}" />`);
  arr.forEach(item => {
    let li = $("<li />");
    if(key !== false)
      item = item[key];
    li.text(item);
    ul.append(li);
  });
  return ul;
}

// transforms li content into disabled text fields
let textareafy = ul => {

  ul.find('li').each((i, li) => {
    let content = $(li).html();
    let ta = $("<textarea></textarea>");
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
      sel.each((i,s)=>{
        s.addEventListener('click', e => {
          if(s.classList.contains('open')) {
            s.classList.remove('open');
            s.style.height = 'auto';
          } else {
            open(s);
            s.classList.add('open');
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
  let setHolder = (label,value) => el.find(`[data-placeholder=${label}]`).text(value);
  return new Promise((resolve, reject) => {

    let { url, datetime, version, requested_urls, signatures, javascript } = data;

    let requestsContainer = el.find('#diary-requests');
    let signaturesContainer = el.find('#diary-signatures');
    let javascriptContainer = el.find('#diary-javascript');

    // fills up placeholders
    setHolder('url', url);
    setHolder('datetime', moment(datetime).format('LLL'));
    setHolder('version', version);

    // creates data fields
    let requestsList = textareafy(generateList(requested_urls, "url"));
    let signaturesList = generateList(signatures, false, "default-list");
    let javascriptList = textareafy(generateList(javascript));

    console.log(signaturesList);

    requestsContainer.append(requestsList.list);
    signaturesContainer.append(signaturesList);
    javascriptContainer.append(javascriptList.list);

    requestsList.render(requestsList.list.find('textarea'));
    javascriptList.render(javascriptList.list.find('textarea'));

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
