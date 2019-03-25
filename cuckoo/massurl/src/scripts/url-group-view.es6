import $ from './jquery-with-plugins';
import moment from 'moment';
import Paginator from './paginator';
import Templates from './templates';
const APIUrl = (endpoint=false) => `/api${endpoint ? endpoint : '/'}`;

const state = {
  g_offset: 0,
  g_limit: 50,
  g_loading: false,
  g_content_end: false
};

const urls = {
  groups: () => APIUrl(`/groups/list`),
  groupUrls: gid => APIUrl(`/group/view/${gid}/urls`),
  diaries: id => APIUrl(`/diary/url/${id}`),
  groupsList: () => {
    state.g_offset += 1;
    let offset = state.g_offset * state.g_limit;
    return APIUrl(`/groups/list?offset=${offset}&details=1`);
  }
}

function loadGroups() {
  return new Promise((resolve, reject) => {
    $.get(urls.groups(), res => resolve(res), rej => reject(rej), "json");
  });
}

// detects a ?view={id} item to pre-open url editors
function detectTarget() {
  let ls = window.localStorage.getItem('ek-selected-group');
  let tgt = window.location.search.replace('?','').split('=');
  if(tgt.length == 2)
    return parseInt(tgt[1]);
  if(ls)
    return parseInt(ls);
  return false;
}

// loads up the urls for a group
function loadUrlsForGroup(groupId) {
  return new Promise((resolve, reject) => {
    $.get(urls.groupUrls(groupId), data => {
      resolve(data);
    }, err => reject(err), "json");
  });
}

// opens a diary for a specific url
function openDiaryForUrl(el, id) {
  window.location = `/diary/${id}`;
}

// returns a list of diaries for a url
function getDiariesForUrl(id) {
  return new Promise((resolve, reject) => {
    $.get(urls.diaries(id), res => resolve(res), err => reject(err), "json")
  });
}

// populates urls for a certain group
function populateUrls(u,el) {

  el.empty();

  // creates a url button
  let createUrlButton = e => {
    let li = $("<li />");
    let ta  = $("<textarea />");
    let ic = $("<i class='far fa-atlas'></i>");
    let ar = $("<i class='far fa-angle-right'></i>");
    li.attr('data-url-id', e.id); // MOCK ID
    ta.val(e.url);
    ta.attr('title', e.url);
    ta.attr('disabled', true);
    li.append(ic, ta, ar);
    return li;
  };

  // creates a list of diaries
  let createDiaryList = diaries => {
    let ul = $("<ul class='data-list scroll-context' />");
    diaries.forEach(diary => {
      let { version, datetime, id } = diary;
      let an = $("<a />");
      let li = $("<li />");
      let sp = $("<span class='tag' data-label-prefix='No.' />");
      an.data('diary', diary);
      an.text(moment(datetime).format('LLL'));
      an.attr('href',`/diary/${id}`);
      sp.attr('title',version);
      an.prepend(sp);
      li.append(an);
      ul.append(li);
    });
    return ul;
  };

  if(u.length) {
    u.map(e => createUrlButton(e)).forEach(e => {
      el.append(e);
      // creates a dropdown list for that group, opens on click
      e.on('click', e => {
        e.preventDefault();
        e.stopPropagation();
        let el = $(e.currentTarget);
        getDiariesForUrl(el.data('urlId')).then(diaries => {
          if(!el.hasClass('open')) {

            let ul = createDiaryList(diaries);
            el.after(ul);
            el.addClass('open');

            // add paginator
            const paginator = new Paginator({
              url: urls.diaries(el.data('urlId')),
              limit: 50,
              offset: 0
            });

            let button = $(`
              <li class="paginate"><button class="button">More</button></li>
            `);

            ul.append(button);

            button.find('button').on('click', e => {
              e.preventDefault();
              e.stopPropagation();
              paginator.next();
            });

            paginator.on('payload', data => {
              let list = createDiaryList(data.response);
              list.find('li').each((i,li)=>{
                button.before(li);
                // if 'no records' is shown, remove it
                if(button.find('p').length) button.find('p').remove();
              });
            });

            paginator.on('empty', () => {
              if(!button.find('p').length)
                button.append('<p><i class="fas fa-exclamation-triangle"></i> No records left.</p>');
            });

          } else {

            el.removeClass('open');
            el.next('.data-list').remove();

          }
        });
      });
    });
  } else {
    // display a message that the list is empty
    let li = $(document.createElement('li'));
    li.text('There are no urls in this group.');
    el.append(li);
  }
}

function initUrlGroupView($el) {

  const pre = [];
  let $groupFilter = $el.find('#filter-group-names');
  let $groups = $el.find('.url-groups');
  let $moreGroups = $el.find('#load-more-groups');
  let $urls = $el.find('.url-list');

  let linkClickHandler = e => {

    e.preventDefault();

    $groups.find('a').removeClass('active');
    $(e.currentTarget).addClass('active');

    let id = e.currentTarget.getAttribute('href').split(':')[1];
    window.localStorage.setItem('ek-selected-group', id);

    loadUrlsForGroup(id).then(d => {
      populateUrls(d.urls, $urls);
    }).catch(err => console.log(err));

    return false;
  }

  return new Promise((resolve, reject) => {

    $el.find('.url-groups a[href^="open:"]').on('click', linkClickHandler);

    $el.find('.url-groups li').each(function() {
      $(this).find('.events-badge').on('click', function() {
        let gn = $(this).parents('li').data('name');
        window.location = `/?group=${gn}`;
      });
    });

    $groupFilter.on('keyup', e => {
      let val = $(e.currentTarget).val();
      $el.find('[data-group-list]').filterList(val);
    });

    let loadMoreGroups = () => {
      if(state.g_loading === true || state.g_content_end === true) return;
      state.g_loading = true;
      $.get(urls.groupsList()).done(groups => {
        if(groups.length) {
          groups.forEach(group => {
            let g = $(Templates.groupListItem(group));
            $el.find('.url-groups').append(g);
            g.find('a').on('click', linkClickHandler);
            g.find('.events-badge').on('click', function() {
              let gn = $(this).parents('li').data('name');
              window.location = `/?group=${gn}`;
            });
          });
          if(groups.length < state.g_limit)
            state.g_content_end = true;
        } else {
          state.g_content_end = true;
        }
        state.g_loading = false;
      });
    }

    $moreGroups.on('click', e => {
      e.preventDefault();
      loadMoreGroups();
    });

    $(".url-groups").on('scroll', () => {
      if($(".url-groups").scrollTop() + $(window).height() > $(".url-groups")[0].scrollHeight)
        loadMoreGroups();
    });

    let show = detectTarget();
    if(show) {
      $(`.url-groups a[href="open:${show}"]`).click();
      // loadUrlsForGroup(show).then(d => {
      //   populateUrls(d.urls, $urls);
      // }).catch(err => console.log(err));
    } else {
      $el.find('.url-groups a[href^="open:"]').eq(0).click();
    }

    resolve();

  });
}

export { initUrlGroupView };
