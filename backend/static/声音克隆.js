window.VoiceCloning = (() => {
  const $=id=>document.getElementById(id);
  let voices=[], sampleURL='', busy=false;
  function message(text){$('clone-status').textContent=text;}
  function render(selected=''){
    const select=$('clone-voices');select.replaceChildren();
    select.add(new Option(voices.length?'选择音色':'还没有个人音色',''));
    voices.forEach(voice=>select.add(new Option(voice.name,voice.id)));
    if(selected)select.value=selected;
    controls();
  }
  function controls(){
    $('clone-create').disabled=busy;
    $('clone-refresh').disabled=busy;
    $('clone-preview').disabled=busy||!$('clone-voices').value;
    $('clone-use').disabled=busy||!$('clone-voices').value;
  }
  async function refresh(){
    message('正在读取个人音色…');
    try{
      const response=await fetch('/api/tts/clone/voices',{signal:AbortSignal.timeout(35000)});
      const data=await response.json();
      if(!response.ok)throw new Error(data.detail?.message || '音色列表读取失败。');
      const selected=$('clone-voices').value;voices=data.voices||[];render(selected);
      message(voices.length?'个人音色已加载，可选择试听。':'暂无个人音色，上传录音后创建。');
    }catch(error){message(error.message || '音色读取失败，请刷新重试。');}
  }
  function init(){
    $('clone-refresh').onclick=refresh;
    $('clone-voices').onchange=controls;
    $('clone-audio').onchange=()=>{
      if(sampleURL)URL.revokeObjectURL(sampleURL);
      const file=$('clone-audio').files[0];const player=$('clone-sample');
      player.hidden=!file;
      if(file){sampleURL=URL.createObjectURL(file);player.src=sampleURL;}
      else player.removeAttribute('src');
    };
    $('clone-create').onclick=async()=>{
      if(busy)return;
      const file=$('clone-audio').files[0],name=$('clone-name').value.trim();
      if(!name||!file){message('请填写音色名称并选择一段录音。');return;}
      if(file.size>10*1024*1024){message('录音不能超过 10 MB。');return;}
      const form=new FormData();form.append('name',name);form.append('audio',file);form.append('reference_text',$('clone-transcript').value.trim());
      busy=true;controls();message('正在创建个人音色，请稍候…');
      try{
        const response=await fetch('/api/tts/clone',{method:'POST',body:form,signal:AbortSignal.timeout(200000)});
        const result=await response.json();
        if(!response.ok)throw new Error(result.detail?.message || '创建失败，请检查录音后重试。');
        voices=[result.voice,...voices.filter(item=>item.id!==result.voice.id)];render(result.voice.id);
        message('个人音色已创建。可以试听，或用于语音合成。');
      }catch(error){message(error.name==='TimeoutError'?'请求超时，请先刷新音色列表确认是否已创建成功。':error.message);}
      finally{busy=false;controls();}
    };
    $('clone-preview').onclick=async()=>{
      if(busy||!$('clone-voices').value)return;
      const text=$('clone-test-text').value.trim();if(!text){message('请填写试听文本。');return;}
      busy=true;controls();message('正在合成试听音频…');
      try{
        const response=await fetch('/api/tts/synthesize',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text,voice:$('clone-voices').value}),signal:AbortSignal.timeout(150000)});
        const data=await response.json();
        if(!response.ok||!data.audio_base64)throw new Error(data.detail?.message || '试听失败，请稍后重试。');
        playTtsAudio(data.audio_base64);message('试听音频已生成。');
      }catch(error){message(error.message || '试听失败，请稍后重试。');}
      finally{busy=false;controls();}
    };
    $('clone-use').onclick=()=>{
      const voice=voices.find(item=>item.id===$('clone-voices').value);if(!voice||!TTS_STATUS)return;
      TTS_ENGINE=TTS_STATUS.provider_id;TTS_STATUS.voice=voice.id;
      const provider=TTS_STATUS.providers.find(item=>item.id===TTS_ENGINE);
      if(provider){provider.voices=[voice,...(provider.voices||[]).filter(item=>item.id!==voice.id)];}
      document.querySelectorAll('#tts-engines .seg-item').forEach(item=>item.classList.toggle('active',item.dataset.engine===TTS_ENGINE));
      fillTtsEngine();
      message('已选用此音色。点击“保存并热生效”可设为默认音色。');
    };
    render();
  }
  return {init,open:refresh};
})();
