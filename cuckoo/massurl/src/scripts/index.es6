import $ from 'jquery';
import Templates from './templates';
import Fullscreen from './fullscreen';

// shifts background based on current state (on/off/toggle)
// swapBackground(null) => toggles
// swapBackground(true/false) => sets .fill-red class based on bool
// => this is for demonstrational purposes. Click the logo to trigger
function alertMode() {
  if($("#app-background").hasClass('fill-red')) {
    // $("#top-level-alert").removeClass('focus');
    $("#app-background").removeClass('fill-red');
  } else {
     // $("#top-level-alert").addClass('focus');
    $("#app-background").addClass('fill-red');
  }
}

// swaps the audio button state. at the moment for demonstrational purposes.
// click the audio icon to toggle and view
function toggleAudio(el) {
  if($(el).find('.fal').hasClass('fa-volume-mute')) {
    $(el).find('.fal').removeClass('fa-volume-mute').addClass('fa-volume-up');
  } else {
    $(el).find('.fal').removeClass('fa-volume-up').addClass('fa-volume-mute');
  }
}

// toggle the fullscreen mode
function toggleFullScreen(el) {
  let icon = el.querySelector('.fal');
  console.log(icon.classList);
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

// toggle-expand the info-row in the table
function expandInfoRow(e) {
  e.preventDefault();
  let row = $(e.currentTarget);
  row.parents('tbody').find('tr.expanded').not(row).removeClass('expanded');
  row.toggleClass('expanded');
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

// shortcut for adding url group
function addURLGroup(id, name, description) {

}

$(function() {

  // global app inits
  $("#toggle-audio").on('click', e => toggleAudio(e.currentTarget));
  $("#toggle-fullscreen").on('click', e => toggleFullScreen(e.currentTarget));
  $("[data-online]").on('click', toggleSystemIndicator);

  // specific inits for event-monitor
  if($("#event-monitor").length) {
    $("#swap-bg").on('click', alertMode);
    $("html").on("keydown", e => hotkey(e.keyCode));
    $("#alert-table").find('tbody > tr').not('.info-expansion').on('click', expandInfoRow);
  }

  // specific inits for url-grouping
  if($("#url-grouping").length) {
    
  }

});
