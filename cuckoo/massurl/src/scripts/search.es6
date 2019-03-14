import moment from 'moment';
import $ from 'jquery';
import Paginator from './paginator';

const APIUrl = (endpoint=false) => `/api/diary/${endpoint ? endpoint : '/'}`;
const urls = {
  search: str => APIUrl(`search?q=${encodeURIComponent(str)}`)
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
        autoIncrement: false,
        limit: 20,
        offset: 0,
        startChar: '&'
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

        result.empty();

        let firstPayload = true;
        let paginate = $("<li class='paginate'><button class='button'>More results</button></li>");

        // paginator.on('request', () => result.html('<i class="fas fa-spinner-third fa-spin"></i>'));

        paginator.on('payload', payload => {

          // set the pagination offset to the next / last datetime (unix ms)
          let nextOffset = payload.response[payload.response.length-1];
          if(nextOffset)
            paginator.offset = nextOffset.datetime;

          let list = createList(payload.response, (li, part) => {
            let { datetime, version, url, id } = part;
            let date = moment.utc(datetime).format('LLL');
            let a = $(`<a href="/diary/${id}" />`);
            a.append(`
              <p class="url">${url}</p>
              <div class="spread">
                <span>No. ${version}</span>
                <span>${date}</span>
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

        paginator.on('empty', () => result.html('<p>No results</p>'));

        paginator.next();

      }).catch(ev => {
        result.html('<p>No results</p>')
      });

      return false;
    });
  });

  resolve();
}

export { initSearch };
