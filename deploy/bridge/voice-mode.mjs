import {loadVoiceCommands,createVoiceCommandClassifier} from './voice-commands.mjs';
// Read once at process startup; editing the file requires an idle restart.
export const voiceCommandConfig=loadVoiceCommands();
export const classifyVoiceCommand=createVoiceCommandClassifier(voiceCommandConfig);
