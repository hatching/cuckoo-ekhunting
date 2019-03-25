import $ from './jquery-with-plugins';
import moment from 'moment';
import autosize from 'autosize';
import Scheduler from './scheduler';
import Templates from './templates';

const APIUrl = (endpoint=false,suf=false) => `/api/group${suf?'s':''}/${endpoint ? endpoint : '/'}`;
const state = {
  g_offset: 0,
  g_limit: 50,
  g_loading: false,
  g_content_end: false
}

const urls = {
  list_groups: () => {
    state.g_offset += 1;
    let offset = state.g_offset * state.g_limit;
    return APIUrl(`list?offset=${offset}&details=1`,true);
  },
  view_groups: (group_id, l = 1000, o = 0) => APIUrl(`view/${group_id}?limit=${l}&offset=${o}&details=1`),
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
        group.urls = [];
        if(u.urls) group.urls = u.urls.map(url => url.url);
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
    return [...textarea[0].value.split(seperator).filter(v => (v !== ""))];
  return [];
}

// sets a schedule for a certain group
function setSchedule(id, schedule='now') {
  return new Promise((resolve, reject) => {
    if(!id) return reject({message:'no ID for schedule'});
    $.post(urls.schedule_group(id), (!schedule ? {} : {schedule}), response => {
      resolve(response);
    }).fail(err => reject(err))
  });
}

// sets a schedule for group id
function scheduleNow(id) {
  return setSchedule(id);
}

// resets a schedule for group id
function scheduleReset(id) {
  return setSchedule(id,false);
}

// opens a pane for group settings
function editorSettings($editor, data) {

  $.get('/api/profile/list').done(profiles => {

    data.profiles = profiles;

    let $settings = $(Templates.groupSettings(data));
    $editor.append($settings);

    $settings.find('#save-group-profiles').on('click', e => {
      $.post(`/api/group/${data.group.id}/profiles`, {
        profile_ids: (function() {
          let sel = [];
          $settings.find('#select-profiles input:checked').each((i,p) => sel.push($(p).val()));
          return sel.join(',');
        }())
      }).done(response => {
        $(`.url-groups a[href="open:${data.group.id}"]`).click();
      }).fail(err => console.log(err));
    });

    $settings.find("#save-group-settings").on('click', e => {
      let values = {
        threshold: parseInt($settings.find('input[name="group-threshold"]').val()),
        batch_size: parseInt($settings.find('input[name="batch-size"]').val()),
        batch_time: parseInt($settings.find('input[name="batch-time"]').val())
      }
      $.post(`/api/group/${data.group.id}/settings`, values).done(response => {
        $(`.url-groups a[href="open:${data.group.id}"]`).click();
      }).fail(err => console.log(err));
    });

    $settings.find('header [data-close]').on('click', e => {
      e.preventDefault();
      $settings.remove();
    });

  }).fail(err => console.log(err));

}

// initializes and renders a url editor for a group
function initEditor(data = {}, $editor) {

  if(!data.template || !$editor) return false;
  $editor.html(data.template);
  let $textfield = $editor.find('textarea');
  let scan = $editor.find('button[data-schedule-now]');

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
        if(a.length) {
          saveUrls(values, id).then(res => {
            loadUrlsForGroup(data.group.id).then(u => {
              // update state
              state.urls = u.urls;
              $(`.url-groups a[href="open:${data.group.id}"]`).click();
            }).catch(e => console.log(e));
          }).catch(e => console.log(e));
        }
      }).catch(e => {
        console.log(e);
      });
    } else {
      saveUrls(values, id).then(res => {
        loadUrlsForGroup(data.group.id).then(u => {
          // update state
          state.urls = u.urls;
          $(`.url-groups a[href="open:${data.group.id}"]`).click();
        }).catch(e => console.log(e));
      }).catch(e => console.log(e));
    }
  });

  $editor.find('[data-settings]').on('click', e => {
    editorSettings($editor, data);
  });

  // initialize scheduler button
  let scheduler = new Scheduler({
    button: document.querySelector('#toggle-scheduler'),
    value: data.group.schedule,
    submit: values => {

      values.when = (function(props) {
        if(props.frequency == 'weekly')
          return `${props.day}`;
        else
          return `${props.days}d`;
      }(values));

      let schedule = `${values.when}@${values.time.hours}:${values.time.minutes}`;

      setSchedule(data.group.id, schedule).then(response => {
        let nextDate = moment();
        if(values.frequency == 'every')
          nextDate.add(parseInt(values.days),'days');
        if(values.frequency == 'weekly')
          nextDate.add(7, 'days');
        nextDate.hours(values.time.hours);
        nextDate.minutes(values.time.minutes);
        nextDate.seconds(0);

        let scheduleString = nextDate.format('YYYY-DD-MM HH:mm:ss');
        scan.find('span').text(scheduleString);
        let $groupListItem = $(`.url-groups li[data-id=${data.group.id}] a`);
        if(!$groupListItem.find('span').length) {
          let sp = $("<span />");
          $groupListItem.append(sp);
        }
        $groupListItem.find('span').html(`<i class="fal fa-calendar-check"></i> ${scheduleString}`);
        $("#toggle-scheduler span").text(`Scheduled at ${scheduleString}`);
        $("#toggle-scheduler i").removeClass('fa-calendar').addClass('fa-calendar-check');
      }).catch(err => console.log(err));

    },
    reset:() => {
      scheduleReset(data.group.id).then(response => {
        $("#toggle-scheduler span").text('Schedule');
        $("#toggle-scheduler i").removeClass('fa-calendar-check').addClass('fa-calendar');
        $(`.url-groups li[data-id=${data.group.id}] a span`).remove();
      }).catch(err => console.log(err));
    }
  });

  $editor.find('button[data-schedule-now]').on('click', e => {
    scheduleNow(data.group.id).then(response => {
      scan.text(response.message.split('.')[0]);
      scan.prop('disabled',true);
      if($editor.find('.next-scan'))
        $editor.find('.next-scan span').text(response.message.replace('Scheduled at ','').split('.')[0]);
    }).catch(err => console.log(err));
  });

  // close the editor
  $editor.find('button[data-close]').on('click', e => {
    $editor.empty().addClass('idle');
  });
}

// detects a ?mng={id} item to pre-open url editors
function detectTarget() {
  let ls = window.localStorage.getItem('ek-selected-group');
  let tgt = window.location.search.replace('?','').split('=');
  if(tgt)
    if(tgt.length == 2)
      return parseInt(tgt[1]);
  if(ls)
    return parseInt(ls);
  return false;
}

// initializes the url management ui
function initUrlManagement($editor) {

  let openAt = detectTarget();
  let $links = $editor.find('.url-groups a[href^="open:"]');
  let detailID = window.EK_Group_ID || false;

  let linkClickHandler = e => {
    let id = parseInt($(e.currentTarget).attr('href').split(':')[1]);
    $editor.find('.editor').empty().removeClass('idle').addClass('loading');
    $(e.currentTarget).parents('ul').find('.active').removeClass('active');
    $(e.currentTarget).addClass('active');
    loadGroup(id)
      .then(data => {
        initEditor(data, $editor.find('#url-edit'));
        window.localStorage.setItem('ek-selected-group', id);
        $editor.find('#url-edit').removeClass('loading idle');
      })
      .catch(err => console.log(err));
    return false;
  }

  return new Promise((resolve, reject) => {

    $links.on('click', e => linkClickHandler(e));

    $links.find('.events-badge').on('click', function() {
      let gn = $(this).parents('li').data('name');
      window.location = `/?group=${gn}`;
    });

    $editor.find('.editor').removeClass('loading');

    $editor.find('#filter-group-names').on('keyup', e => {
      let val = $(e.currentTarget).val();
      $editor.find('[data-group-list]').filterList(val);
    });

    let loadMoreGroups = () => {
      if(state.g_loading === true || state.g_content_end === true) return;
      state.g_loading = true;
      $.get(urls.list_groups()).done(groups => {
        if(groups.length) {
          groups.forEach(group => {
            let g = $(Templates.groupListItem(group));
            $editor.find('.url-groups').append(g);
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

    $editor.find('#load-more-groups').on('click', e => {
      e.preventDefault();
      loadMoreGroups();
    });

    $(".url-groups").on('scroll', () => {
      if($(".url-groups").scrollTop() + $(window).height() > $(".url-groups")[0].scrollHeight)
        loadMoreGroups();
    });

    if(openAt) {
      if($editor.find(`.url-groups a[href="open:${openAt}"]`).length) {
        // if existent, click the selected openAt group
        $editor.find(`.url-groups a[href="open:${openAt}"]`).trigger('click');
      } else {
        // else, load it up through the API
        loadGroup(openAt)
          .then(data => {
            initEditor(data, $editor.find('#url-edit'));
            $editor.find('#url-edit').removeClass('loading idle');
          })
          .catch(err => console.log(err));
      }
    } else {
      $editor.find('.editor').addClass('idle');
    }

    resolve();
  });
}

export {
  initUrlManagement
};
