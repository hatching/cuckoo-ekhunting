import Handlebars from 'handlebars';

const soundClipPath = '/static/sounds/';

const availableSounds = [
  'boop',
  'peter-rekts-a-wolf',
  'ploop',
  'taduh',
  'upping'
]

function renderAvailableSoundsList() {
  let html = data => Handlebars.compile(`
    <ul>
      {{#each sounds}}
        <li><a href="#">{{this}}</a></li>
      {{/each}}
    </ul>
  `);
  return html({sounds:availableSounds});
}

// util - string bool to bool
function stringToBoolean(val){
  let a = {
    'true':true,
    'false':false
  };
  return a[val];
}

export default function sound(name) {
  if(availableSounds.indexOf(name) == -1) return false;
  if(stringToBoolean(localStorage.getItem('play-audio')) === false) return false;
  let a = new Audio(`${soundClipPath}/${name}.mp3`);
  a.play();
  return true;
}

export { renderAvailableSoundsList as soundList };
