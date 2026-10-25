// Local controls are handled before the audio ownership gate; questions stay gated.
export async function dispatchNativeText(voice,controller,text){
 if(!text)return false;
 if(await voice?.onNativeText(text))return true;
 if(voice?.nativeBlocked())return false;
 await controller.onText(text);return true;
}
