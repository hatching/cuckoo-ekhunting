import moment from 'moment';
import $ from 'jquery';
import Paginator from './paginator';

const APIUrl = (endpoint=false) => `/api/diary/${endpoint ? endpoint : '/'}`;
const urls = {
  search: str => APIUrl(`search/${str}`)
}

function createList(data,format) {
  let ul = $("<ul class='data-list clear-margin' />");
  data.forEach(item => {
    let li = $("<li />");
    li = format(li,item);
    ul.append(li);
  });
  return ul;
}

// generates a Paginator for this specific value call (offset&limit)
function search(el, val) {
  return new Promise((resolve, reject) => {
    if(val.length) {
      resolve(new Paginator({
        url: urls.search(val),
        limit: 20,
        offset: 0
      }));
    } else {
      reject('empty');
    }
  });
}

function initSearch(el, result) {
  let input = el.find('input');
  return new Promise((resolve, reject) => {
    el.on('submit', e => {
      e.preventDefault();
      search($(e.currentTarget), input.val()).then(paginator => {

        let firstPayload = true;
        let paginate = $("<li class='paginate'><button class='button'>More results</button></li>");

        paginator.on('payload', payload => {

          let list = createList(payload.response, (li, part) => {
            let { datetime, version, url, id } = part;
            let date = moment(datetime).format('LLL');
            let a = $(`<a href="/diary/${id}" />`);
            a.append(`
              <p class="url">${url}</p>
              <div class="spread">
                <span>${version}</span>
                <span>${datetime}</span>
              </div>
            `);
            li.append(a);
            return li;
          }, "url");

          if(firstPayload) {
            list.append(paginate);
            paginate.find('button').on('click', e => paginator.next());
            result.html(list);
          } else {
            list.find('li').each((i, item) => paginate.before(item));
          }

          firstPayload = false;

        });

        paginator.on('error', err => {
          console.log(err);
        });

        paginator.next();

      }).catch(ev => console.log(ev));
      return false;
    });
  });

  resolve();
}

export { initSearch };
