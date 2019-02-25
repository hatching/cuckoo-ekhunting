import $ from './jquery-with-plugins';
import Templates from './templates';
import stream from './socket-handler';
import sound from './sounds';

const baseUrl = `${window.location.origin}/api/alerts`;
const socketBase = `ws://${window.location.host}/ws/alerts`;

function parseGroupName() {
  if(window.location.search) {
    let str = ""+window.location.search.replace('?','');
    let spl = str.split('=');
    if(spl[0] == 'group')
      return spl[1];
  }
  return false;
}

const urls = {
  alerts: (l,o,s='desc',ob='timestamp') => {
    let u = `${baseUrl}/list?limit=${l}&offset=${o*l}&order=${s}&orderby=${ob}`
    let g = parseGroupName();
    if(g) u += `&group_name=${g}`;
    return u;
  },
  alertRead: () => `${baseUrl}/read`
}

let currentLimit = 20;
let currentOffset = 0;

const state = {
  topAlert: false
}

// shifts background based on current state (on/off/toggle)
// swapBackground(null) => toggles
// swapBackground(true/false) => sets .fill-red class based on bool
// => this is for demonstrational purposes. Click the logo to trigger
function alertMode(toggle = null) {
  if(toggle === null) {
    if($("#app-background").hasClass('fill-red')) {
      $("#app-background").removeClass('fill-red');
    } else {
      $("#app-background").addClass('fill-red');
      sound('boop');
    }
  } else {
    $("#app-background").toggleClass('fill-red', toggle);
  }
}

// demonstrative function
function loopSocket() {
  setInterval(() => {
    let notify = [true,false][Math.floor(Math.random() * 2)];
    let lvl = [1,2,3][Math.floor(Math.random() * 3)];
    $.get(`${window.location.origin}/genalert?level=${lvl}&notify=${notify}`, response => {
      console.log(`generated alert [level: ${lvl}] [notify: ${notify}]`);
    });
  }, 10000);
}

function connectSocket(cb) {
  return new Promise((resolve, reject) => {
    let iv = 3000;
    let str = stream(socketBase, {
      onmessage: r => cb ? cb(JSON.parse(r)) : null,
      onerror: () => reject('Websocket returned an error')
    }, iv, false);
    resolve(str);
  });
}

function setAlertRead(data={}) {
  return new Promise((resolve, reject) => {
    $.post(urls.alertRead(), data).done(response => {
      if(data.alert && state.topAlert)
        if(data.alert == state.topAlert.id) state.topAlert.read = true;
      resolve(response);
    }).fail(err => reject(err));
  });
}

function createInfoRow(alert, parent) {

  // remove if it already exists
  if(parent.next().hasClass('info-expansion')) {
    parent.removeClass('expanded');
    parent.next().remove();
    return;
  }
  let row = $(Templates.eventInfo(alert));
  parent.after(row);
  parent.addClass('expanded');

  setAlertRead({
    alert: alert.id
  }).then(r => {
    parent.find('td:first-child').removeClass('fill-base');
  }).catch(e => console.log(e));
}

function topAlert($table, alert) {

  // populate alert in top-level
  $("#top-level-alert").addClass('out');

  setTimeout(() => {
    let newContent = $(Templates.topEvent(alert));

    $("#top-level-alert .alert-outer").html(newContent);

    newContent.find('.button').on('click', e => {
      $table.find(`tr[data-id=${alert.id || alert.task_id}]`).trigger('click');
    });

    setTimeout(() => {
      $("#top-level-alert").removeClass('out');
    }, 500);

  }, 300);

  state.topAlert = alert;

  if(alert.notify)
    alertMode();
}

function addAlert(alert, $table, method='append', first=false) {

  // pre-reset the alert mode
  alertMode(false);

  // create table entry
  let el = $(Templates.event(alert));

  $table.find('tbody')[method](el);

  el.on('click', e => {
    if($(e.currentTarget).hasClass('info-expansion')) return;
    if($(e.target).prop('tagName').toLowerCase() == 'a') return;
    createInfoRow(alert, el);
  });

  if(!first) {
    if(state.topAlert && !state.topAlert.read) {
      if(state.topAlert.level == 3 && alert.level < 3) return;
    }
    topAlert($table, alert);
  }

  if(!alert.read && $("#mark-group-alerts-read i").hasClass('fa-comment-alt'))
    $("#mark-group-alerts-read i")
      .removeClass('fa-comment-alt')
      .addClass('fa-comment-alt-check');

}

function paginateNext() {
  return new Promise((resolve, reject) => {
    currentOffset += 1;
    console.log(`fetching page ${currentOffset}, retrieving ${currentLimit} more alerts.`);
    $.get(urls.alerts(currentLimit,currentOffset), response => resolve(response))
      .fail(err => reject(err));
  });
}

function initAlerts($table) {

  const gid = parseGroupName();

  const response = {
    alerts: [],
    html: '',
    jq: function() {
      return $(this.html);
    }
  };

  $table.find('#paginate-next').on('click', e => {
    e.preventDefault();
    paginateNext().then(response => {
      if(response.length)
        response.forEach(alert => addAlert(alert, $table));
    }).catch(err => console.log(err));
  });

  //
  // initialize sorting on table
  //
  $table.find('th.sortable').each(function() {

    let th = $(this),
        index = th.index(),
        inverse = false;

    // force click upon th
    th.find('a').on('click', e => e.preventDefault());

    function moveInfoBlocks() {
      $table.find('tr[data-id]').each(function() {
        let id = $(this).data('id');
        let targetInfoRow = $table.find(`tr[data-belongs-to="${id}"]`);
        $(this).insertAfter(targetInfoRow);
      });
    }

    th.on('click', e => {
      $table.find('td').filter(function() {
        return $(this).index() === index;
      }).sortElements(function(a,b) {
        if(a.getAttribute('data-sort-number')) {
          a = parseInt(a.getAttribute('data-sort-number'));
          b = parseInt(b.getAttribute('data-sort-number'));
          return a > b ?
            inverse ? -1 : 1
            : inverse ? 1 : -1;
        } else {
          return $.text([a]) > $.text([b]) ?
            inverse ? -1 : 1
            : inverse ? 1 : -1;
        }
      }, function() {
        return this.parentNode;
      });
      inverse = !inverse;
    });

  });

  return new Promise((resolve, reject) => {

    $.get(urls.alerts(currentLimit,currentOffset), alerts => {

      // constructs available alerts from API call
      response.alerts = alerts || [];

      alerts.forEach(alert => addAlert(alert, $table));

      if($table.find('tr.loading').length)
        $table.find('tr.loading').remove();

      // set first alert to pop
      topAlert($table, alerts[0]);

      connectSocket(alert => {
        if(gid && alert.url_group_name !== decodeURIComponent(gid)) return;
        addAlert(alert, $table, 'prepend');
      }).then(str => {
        response.stream = str;
        resolve(response || {});
      }).catch(e => reject(e));

      if(gid) {

        $('.app__header .controls').prepend(`
          <li>
            <button id="mark-group-alerts-read" title="Mark all alerts read">
              <i class="fal fa-comment-alt-check"></i>
            </button>
          </li>
        `);

        let setToCompleted = () => $("#mark-group-alerts-read i")
                                      .removeClass('fa-comment-alt-check')
                                      .addClass('fa-comment-alt');

        if(alerts.filter(a=>(a.read==false)).length == 0)
          setToCompleted();

        $('#mark-group-alerts-read').on('click', evt => {
          setAlertRead({
            url_group_name: decodeURIComponent(gid),
            markall: true
          }).then(() => {
            $table.find('.fill-base').removeClass('fill-base');
            setToCompleted()
          }).catch(err => console.log(err));
        });

      }

    }).fail(err => reject({err}));

  });
}

export {
  initAlerts
}
