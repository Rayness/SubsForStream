const socket = io({transports:['websocket'], upgrade:false, autoConnect:false});
const captions = document.querySelector('#captions');
const cards = new Map();
let config = {}, fadeDelay = 5000, maxSpeakers = 6;

function trimCards() {
  while (cards.size > maxSpeakers) removeCard(cards.keys().next().value);
  captions.style.setProperty('--visible-count', Math.max(1,cards.size));
  captions.classList.toggle('many',cards.size>4);
}
function removeCard(id) {
  const card = cards.get(id);
  if (!card) return;
  clearTimeout(card.timer); clearTimeout(card.removal);
  card.el.remove(); cards.delete(id);
  captions.style.setProperty('--visible-count',Math.max(1,cards.size));
  captions.classList.toggle('many',cards.size>4);
}
function hideCard(id) {
  const card=cards.get(id);
  if (!card) return;
  clearTimeout(card.timer);
  card.el.classList.add('out');
  card.removal=setTimeout(()=>removeCard(id),document.body.dataset.anim==='none'?0:160);
}
function showCaption(packet) {
  if (packet.clear) { for(const id of [...cards.keys()]) removeCard(id); return; }
  const speaker=packet.speaker || {id:'self',name:config.speaker_name||'Я',color:'#60a5fa'};
  const id=speaker.id;
  if (!packet.text) { hideCard(id); return; }
  let card=cards.get(id);
  if (!card) {
    const el=document.createElement('section');
    el.className='caption'+(id==='self'?' self':''); el.dataset.speaker=id;
    const label=document.createElement('header'); label.className='speaker';
    const dot=document.createElement('span'); dot.className='speaker-dot';
    const name=document.createElement('span'); name.className='speaker-name';
    label.append(dot,name);
    const text=document.createElement('div'); text.className='caption-text';
    el.append(label,text); captions.append(el);
    card={el,name,text,timer:null,removal:null}; cards.set(id,card);
  }
  clearTimeout(card.timer); clearTimeout(card.removal);
  card.el.classList.remove('out');
  card.name.textContent=speaker.name;
  card.el.style.setProperty('--speaker',/^#[0-9a-f]{6}$/i.test(speaker.color)?speaker.color:'#60a5fa');
  if(card.text.textContent!==packet.text) card.text.textContent=packet.text;
  // Refresh eviction order without reordering the DOM on every word.
  cards.delete(id); cards.set(id,card); trimCards();
  card.timer=setTimeout(()=>hideCard(id),packet.remaining_ms??fadeDelay);
  if(packet.seq && packet.probe) requestAnimationFrame(()=>socket.emit('rendered',{seq:packet.seq}));
}
function applySettings(settings) {
  const root=document.documentElement.style;
  const variables={font_size:'--font-size',font_color:'--font-color',font_family:'--font-family',font_weight:'--weight',font_style:'--style',text_decoration:'--decoration',text_align:'--align',max_width:'--width',bg_css:'--bg'};
  for(const [key,variable] of Object.entries(variables)) {
    if(key in settings) root.setProperty(variable,settings[key]+(key==='font_size'?'px':key==='max_width'?'%':''));
  }
  if('fade_delay' in settings) fadeDelay=settings.fade_delay;
  if('max_speakers' in settings) { maxSpeakers=settings.max_speakers; trimCards(); }
  if(settings.subtitle_theme) document.body.dataset.theme=settings.subtitle_theme;
  if(settings.position) document.body.dataset.position=settings.position;
  if(settings.anim_type) document.body.dataset.anim=settings.anim_type;
  if('show_speakers' in settings) document.body.classList.toggle('hide-speakers',!settings.show_speakers);
  if('bubble_style' in settings) document.body.classList.toggle('legacy-bubble',settings.bubble_style && document.body.dataset.theme==='classic');
  if('text_shadow' in settings) root.setProperty('--shadow',settings.text_shadow?'0 2px 3px #000,0 0 4px #000':'none');
  if(settings.speaker_name && cards.has('self')) cards.get('self').name.textContent=settings.speaker_name;
}
function applyConfig(cfg) {
  config=cfg;
  const rgb=cfg.bg_color.match(/[0-9a-f]{2}/gi).map(x=>parseInt(x,16));
  applySettings({...cfg,fade_delay:cfg.fade_delay*1000,font_weight:cfg.font_bold?'bold':'normal',font_style:cfg.font_italic?'italic':'normal',text_decoration:cfg.font_underline?'underline':'none',bg_css:`rgba(${rgb.join(',')},${cfg.bg_opacity/100})`});
}
socket.on('subtitle',showCaption);
socket.on('settings',applySettings);
socket.on('config_snapshot',applyConfig);
socket.on('connect',()=>socket.emit('overlay_ready'));
socket.on('disconnect',()=>{ for(const id of [...cards.keys()]) removeCard(id); });
socket.connect();
