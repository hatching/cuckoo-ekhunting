import $ from 'jquery';
import autosize from 'autosize';
import Scheduler from './scheduler';
import Templates from './templates';

const APIUrl = (endpoint=false) => `/api/group/${endpoint ? endpoint : '/'}`;

const urls = {
  view_groups: (group_id, l = 1000, o = 0) => APIUrl(`view/${group_id}?limit=${l}&offset=${o}`),
  view_urls: group_id => APIUrl(`view/${group_id}/urls`),
  save_urls: () => APIUrl(`add/url`),
  delete_urls: () => APIUrl('delete/url'),
  schedule_group: id => APIUrl(`schedule/${id}`)
}

// returns all the urls for a specific group
function loadUrlsForGroup(group_id) {
  return new Promise((resolve, reject) => {
    $.get(urls.view_urls(group_id), response => resolve(response)).fail(err => reject(err));
  });
}

// loads up a group from an id
function loadGroup(id) {
  return new Promise((resolve, reject) => {
    $.get(urls.view_groups(id), group => {
      loadUrlsForGroup(group.id).then((u = {urls:null}) => {
        // group.urls = u.urls || [];
        group.urls = [];
        if(u.urls) {
          group.urls = u.urls.map(url => url.url);
        }
        resolve({
          group,
          template: $(Templates.editor(group))
        });
      }).catch(err => reject(err));
    }).fail(err => reject(err));
  })
}

// saves urls to a group
function saveUrls(u = false, id = null) {
  return new Promise((resolve, reject) => {
    $.post(urls.save_urls(), {
      group_id: id,
      urls: u
    }, response => resolve(response)).fail(err => reject(err));
  })
}

// deletes a bunch of urls from a group
function deleteUrls(u = false, id = null) {
  return new Promise((resolve, reject) => {
    $.post(urls.delete_urls(), {
      group_id: id,
      urls: u
    }, response => resolve(response)).fail(err => reject(err));
  });
}

// parses textarea content to array using separator [s]
function textAreaToArray(textarea, seperator = "\n") {
  if(textarea)
    return [...textarea[0].value.split(seperator)];
  return [];
}

// sets a schedule for a certain group
function setSchedule(id, schedule='now') {
  return new Promise((resolve, reject) => {
    if(!id) return reject({message:'no ID for schedule'});
    $.post(urls.schedule_group(id), {schedule}, response => resolve(response)).fail(err => reject(err))
    // $.ajax({
    //   type: 'POST',
    //   url: `/api/groups/schedule/${id}`,
    //   data: JSON.stringify(),
    //   success: response => resolve({success:true,scheduled:id,response}),
    //   error: error => reject({success:false,error})
    // });
  });
}

// initializes and renders a url editor for a group
function initEditor(data = {}, $editor) {

  if(!data.template || !$editor) return false;
  $editor.html(data.template);
  let $textfield = $editor.find('textarea');
  // initialize textarea auto-type-resizer
  autosize($textfield);

  // something about data storage
  let state = {
    urls: [...data.group.urls]
  }

  // returns a list of the 'removed' entries based on the originally loaded
  // urls state for the group.
  let diffRemoved = arr => state.urls.filter(url => arr.indexOf(url) == -1);

  $editor.find('button[data-save]').on('click', e => {
    let values = $textfield.val();
    let id = $(e.currentTarget).attr('data-save');

    let a = textAreaToArray($textfield);
    let rm = diffRemoved(a).join("\n");

    if(rm.length) {
      deleteUrls(rm, data.group.id).then(res => {
        console.log(res);
        saveUrls(values, id).then(res => {
          loadUrlsForGroup(data.group.id).then(u => {
            // update state
            state.urls = u.urls;
          }).catch(e => console.log(e));
        }).catch(e => console.log(e));
      }).catch(e => {
        console.log(e);
      });
    } else {
      saveUrls(values, id).then(res => {
        loadUrlsForGroup(data.group.id).then(u => {
          // update state
          state.urls = u.urls;
        }).catch(e => console.log(e));
      }).catch(e => console.log(e));
    }

  });

  // initialize scheduler button
  let scheduler = new Scheduler({
    button: document.querySelector('#toggle-scheduler'),
    value: false,
    submit: values => {
      console.debug('Scheduler performs [SET schedule]');
      values.when = (function(props) {
        if(props.frequency == 'weekly')
          return `${props.day}`;
        else
          return `${props.days}d`;
      }(values));
      let schedule = `${values.when}@${values.time.hours}:${values.time.minutes}`;
      setSchedule(data.group.id, schedule).then(response => {
        console.log(response);
      }).catch(err => console.log(err));
    },
    reset:() => {
      console.debug('Scheduler performs [RESET schedule]');
    }
  });

  // close the editor
  $editor.find('button[data-close]').on('click', e => {
    $editor.empty().addClass('idle');
  });
}

// detects a ?mng={id} item to pre-open url editors
function detectTarget() {
  let tgt = window.location.search.replace('?','').split('=');
  if(tgt.length == 2) {
    return parseInt(tgt[1]);
  } else {
    return false;
  }
}

// initializes the url management ui
function initUrlManagement($editor) {

  let openAt = detectTarget();
  let $links = $editor.find('.url-groups a[href^="open:"]');
  let detailID = window.EK_Group_ID || false;

  return new Promise((resolve, reject) => {

    $links.on('click', e => {
      e.preventDefault();
      let id = parseInt($(e.currentTarget).attr('href').split(':')[1]);
      $editor.find('.editor').empty().removeClass('idle').addClass('loading');
      $links.removeClass('active');
      $(e.currentTarget).addClass('active');
      loadGroup(id)
        .then(data => {
          initEditor(data, $editor.find('#url-edit'));
          $editor.find('#url-edit').removeClass('loading idle');
        })
        .catch(err => console.log(err));
    });

    $editor.find('.editor').removeClass('loading');

    if(openAt) {
      $editor.find(`.url-groups a[href="open:${openAt}"]`).trigger('click');
    } else {
      $editor.find('.editor').addClass('idle');
    }

    resolve();
  });
}

export {
  initUrlManagement
};
