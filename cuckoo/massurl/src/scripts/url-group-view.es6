import $ from 'jquery';
const APIUrl = (endpoint=false) => `/api${endpoint ? endpoint : '/'}`;

const urls = {
  groupUrls: gid => APIUrl(`/group/view/${gid}/urls`)
}

// loads up the urls for a group
function loadUrlsForGroup(groupId) {
  return new Promise((resolve, reject) => {
    $.get(urls.groupUrls(groupId), data => {
      resolve(data);
    }, err => reject(err), "json");
  });
}

function openDiaryForUrl() {

}

// populates urls for a certain group
function populateUrls(u,el) {
  el.empty();
  if(u.length) {
    u.map(e => {
      let li = $(document.createElement('li'));
      let a  = $(document.createElement('textarea'));
      let icon = $("<i class='far fa-atlas'></i>");
      a.val(e);
      a.attr('disabled', true);
      li.append(icon, a);
      return li;
    }).forEach(e => {
      el.append(e);
      e.on('click', e => {
        e.preventDefault();
        openDiaryForUrl(e.currentTarget.value);
      })
    });
  } else {
    let li = $(document.createElement('li'));
    li.text('There are no urls in this group.');
    el.append(li);
  }
}

function initUrlGroupView($el) {

  let $groups = $el.find('.url-groups a[href^="open:"]');
  let $urls = $el.find('.url-list');

  return new Promise((resolve, reject) => {

    $el.find('.url-groups a[href^="open:"]').on('click', e => {
      $groups.removeClass('active');
      $(e.currentTarget).addClass('active');
      e.preventDefault();
      let id = parseInt(e.currentTarget.getAttribute('href').split(':')[1]);
      // hello world
      loadUrlsForGroup(id).then(d => {
        console.log(d);
        populateUrls(d.urls, $urls);
      }).catch(err => console.log(err))
    });

    $el.find('.url-groups a[href^="open:"]').eq(0).click();

    resolve();
  });
}

export { initUrlGroupView };
