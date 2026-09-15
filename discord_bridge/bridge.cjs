/* Local audio bridge. No chat messages, recordings, or third-party ASR services. */
const {Client, GatewayIntentBits, ChannelType, Events} = require('discord.js');
const {joinVoiceChannel, entersState, VoiceConnectionStatus, EndBehaviorType} = require('@discordjs/voice');
const {OpusEncoder} = require('@discordjs/opus');
const readline = require('node:readline');
let client, connection, closing=false, blocked=false, started=false;
const listeners=new Map(), members=new Map(), gaps=new Set();

function send(message) {
  if(closing) return;
  if(message.event==='audio' && blocked) { gaps.add(message.id); return; }
  if(message.event==='audio' && gaps.delete(message.id)) message.gap=true;
  if(!process.stdout.write(JSON.stringify(message)+'\n')) blocked=true;
}
process.stdout.on('drain',()=>{blocked=false;});
function fail(message) { send({event:'error',message}); shutdown(1); }
function shutdown(code=0) {
  if(closing) return;
  closing=true;
  for(const stream of listeners.values()) stream.destroy();
  connection?.destroy(); client?.destroy();
  process.exitCode=code;
  setTimeout(()=>process.exit(code),100).unref();
  input.close(); process.stdin.destroy();
}
const input=readline.createInterface({input:process.stdin});
input.on('close',()=>shutdown());
process.on('SIGTERM',()=>shutdown());
process.on('uncaughtException',()=>fail('Ошибка Discord-моста. Переподключите бота.'));
process.on('unhandledRejection',()=>fail('Ошибка подключения Discord. Проверьте токен, доступ к каналу и интернет.'));

function nameOf(id, channel) {
  return channel.guild.members.cache.get(id)?.displayName || client.users.cache.get(id)?.globalName || client.users.cache.get(id)?.username || `Участник ${id.slice(-4)}`;
}
async function connect(config) {
  if(!/^\d{15,22}$/.test(config.channel) || typeof config.token!=='string' || !config.token.trim()) {
    fail('Укажите токен бота и ID голосового канала.'); return;
  }
  const limit=Math.max(1,Math.min(8,Number(config.limit)||6));
  client=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildVoiceStates]});
  client.on(Events.Error,()=>send({event:'error',message:'Ошибка Discord. Проверьте подключение.'}));
  client.once(Events.ClientReady,async()=>{
    const channel=await client.channels.fetch(config.channel);
    if(!channel || channel.type!==ChannelType.GuildVoice) { fail('Бот должен иметь доступ к обычному голосовому каналу сервера.'); return; }
    connection=joinVoiceChannel({channelId:channel.id,guildId:channel.guild.id,adapterCreator:channel.guild.voiceAdapterCreator,selfDeaf:false,selfMute:true});
    connection.on('error',()=>send({event:'error',message:'Ошибка голосового соединения Discord.'}));
    connection.on(VoiceConnectionStatus.Disconnected,async()=>{
      send({event:'status',message:'Переподключение Discord…'});
      try { await entersState(connection,VoiceConnectionStatus.Ready,15000); }
      catch { fail('Соединение Discord потеряно. Подключитесь снова.'); }
    });
    await entersState(connection,VoiceConnectionStatus.Ready,30000);
    send({event:'status',message:`Подключено: ${channel.name}. Ожидание речи…`});
    const receiver=connection.receiver;
    receiver.speaking.on('start',id=>{
      if(closing || id===config.ignore || id===client.user.id || listeners.has(id)) return;
      if(channel.guild.members.cache.get(id)?.user.bot) return;
      if(!members.has(id)) {
        if(members.size>=limit) { send({event:'status',message:`Достигнут лимит ${limit} участников. Увеличьте его или переподключите бота.`}); return; }
        members.set(id,nameOf(id,channel));
        send({event:'speaker',id,name:members.get(id)});
        // Resolve a missing nickname without holding the first audio packets.
        channel.guild.members.fetch(id).then(member=>{
          if(!closing && members.has(id)) { members.set(id,member.displayName); send({event:'speaker',id,name:member.displayName}); }
        }).catch(()=>{});
      }
      const decoder=new OpusEncoder(16000,1); // libopus resamples/downmixes natively.
      const stream=receiver.subscribe(id,{end:{behavior:EndBehaviorType.AfterSilence,duration:300}});
      listeners.set(id,stream);
      stream.on('data',packet=>{
        try { send({event:'audio',id,pcm:decoder.decode(packet).toString('base64')}); }
        catch { gaps.add(id); }
      });
      stream.on('error',()=>{gaps.add(id); send({event:'status',message:`Не удалось принять часть аудио: ${members.get(id) || id}.`});});
      stream.on('close',()=>listeners.delete(id));
    });
    client.on(Events.VoiceStateUpdate,(oldState,newState)=>{
      const id=newState.id;
      if(oldState.channelId===channel.id && newState.channelId!==channel.id) {
        listeners.get(id)?.destroy(); listeners.delete(id);
        if(members.delete(id)) send({event:'leave',id});
      }
    });
  });
  try { await client.login(config.token.trim()); }
  catch { fail('Вход не выполнен. Проверьте токен бота и подключение к Discord.'); }
  finally { config.token=''; }
}
input.on('line',line=>{
  if(started) return;
  started=true;
  try { connect(JSON.parse(line)); }
  catch { fail('Неверные параметры запуска Discord-моста.'); }
});

if(process.argv.includes('--check')) {
  const encoder=new OpusEncoder(48000,2), decoder=new OpusEncoder(16000,1);
  const decoded=decoder.decode(encoder.encode(Buffer.alloc(960*2*2)));
  if(decoded.length!==640) throw new Error('Opus conversion failed');
  send({event:'check',ok:true,pcm_bytes:decoded.length}); shutdown();
}
