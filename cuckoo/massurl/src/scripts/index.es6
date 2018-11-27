import $ from 'jquery';
import Fullscreen from './fullscreen';
import { initAlerts } from './alerts';
import { initUrlGroups } from './url-groups';
import { initUrlManagement } from './url-management';
import { initUrlGroupView } from './url-group-view';
import { initDiary } from './diary';

// util - string bool to bool
function stringToBoolean(val){
  let a = {
    'true':true,
    'false':false
  };
  return a[val];
}

// swaps the audio button state. at the moment for demonstrational purposes.
// click the audio icon to toggle and view
function toggleAudio(el, force = null) {

  let activate = () => {
    localStorage.setItem('play-audio', 'true');
    $(el).find('.fal').removeClass('fa-volume-mute').addClass('fa-volume-up');
  }

  let deactivate = () => {
    localStorage.setItem('play-audio', 'false');
    $(el).find('.fal').removeClass('fa-volume-up').addClass('fa-volume-mute');
  }

  if(force === null) {
    let cur = stringToBoolean(localStorage.getItem('play-audio'));
    if(cur === true) {
      deactivate();
    } else if(cur === false) {
      activate();
    }
  } else {
    if(force === true) {
      activate();
    } else if(force === false) {
      deactivate();
    }
  }

}

// toggle the fullscreen mode
function toggleFullScreen(el) {
  let icon = el.querySelector('.fal');
  if(!Fullscreen.active()) {
    icon.classList.remove('fa-expand-alt');
    icon.classList.add('fa-compress-alt');
    Fullscreen.open(document.body);
  } else {
    icon.classList.remove('fa-compress-alt');
    icon.classList.add('fa-expand-alt');
    Fullscreen.close();
  }
}

// toggles the different colors of the color indicator
function toggleSystemIndicator() {
  let ind = $(".app__header .controls .system-indicator");
  let states = ['true','false','error'];
  let curPos = states.indexOf(ind.attr('data-online'));
  ind.attr('data-online', states[curPos+1] || states[0]);
}

function hotkey(key) {
  let tableIsExpanded = () => $("#alert-table tbody tr.expanded").length > 0;
  switch(key) {
    // handle ENTERpress (table: expand the first table row IF nothing is expanded)
    // elsewise mimic 'close' behavior
    case 13:
      if(!tableIsExpanded()) {
        $("#alert-table tbody tr:first-child").trigger('click');
      } else {
        $('#alert-table tbody tr.expanded').trigger('click');
      }
    break;
    // handle RIGHTpress (table: expand next row FROM expanded - otherwise ignore)
    case 39:
      if(tableIsExpanded()) $("#alert-table tr.expanded").next(".info-expansion").next('tr').trigger("click");
    break;
    // handle LEFTpress (table: expand previous row FROM expanded - otherwise ignore)
    case 37:
      if(tableIsExpanded()) $("#alert-table tr.expanded").prev(".info-expansion").prev('tr').trigger("click");
    break;
  }
}

$(function() {

  if(localStorage.getItem('play-audio') === null) {
    toggleAudio($("#toggle-audio"), false);
  } else {
    toggleAudio($("#toggle-audio"), stringToBoolean(localStorage.getItem('play-audio')));
  }

  // global app inits
  $("#toggle-audio").on('click', e => toggleAudio(e.currentTarget));
  $("#toggle-fullscreen").on('click', e => toggleFullScreen(e.currentTarget));
  $("[data-online]").on('click', toggleSystemIndicator);

  // specific inits for event-monitor
  if($("#event-monitor").length) {
    initAlerts($("#alert-table")).then(data => {
      $("html").on("keydown", e => hotkey(e.keyCode));
    }).catch(e => console.log(e));
  }

  // specific inits for url-grouping
  if($("main#url-grouping").length) {
    initUrlGroups($("#url-groups").parents('form')).then(data => {

    });
  }

  // specific inits for url-management
  if($("main#url-management").length) {
    initUrlManagement($("#url-management")).then(data => {

    });
  }

  // specific inits for url-group-view
  if($("main#url-group-view").length) {
    initUrlGroupView($("#url-group-view")).then(data => {

    });
  }

  // specific inits for diary
  if($("main#url-diary").length) {
    initDiary($("#url-diary"), parseInt($("#url-diary").data('urlId'))).then(data => {
      
    });
  }

});
