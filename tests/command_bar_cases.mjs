import {
  parseCommand, resolveCommand, killRoutePresent, KILL_ROUTE_PATTERN,
} from "../app/static/state.mjs";

const missionId = "11111111-1111-4111-8111-111111111111";
const agentId = "22222222-2222-4222-8222-222222222222";
const questionId = "q-open";
const cases = {};

cases.empty = parseCommand("   ");
cases.stop = parseCommand("stop");
cases.stopSlash = parseCommand("/stop");
cases.stopCase = parseCommand("STOP");
cases.stopExtra = parseCommand("stop now");
cases.stopAll = parseCommand("stop-all");
cases.stopAllWords = parseCommand("stop all");
cases.stopAllOneWord = parseCommand("stopall");
cases.stopAllExtra = parseCommand("stop all now");
cases.killBare = parseCommand("kill");
cases.killId = parseCommand("kill " + agentId);
cases.killExtra = parseCommand("kill " + agentId + " extra");
cases.answerEmpty = parseCommand("answer");
cases.answerText = parseCommand("answer ship it");
cases.unknown = parseCommand("pause everything");
cases.unknownNatural = parseCommand("Prioritize deployment.");

const live = {missionId, preview: false, pendingQuestionId: questionId, selectedAgentId: agentId, killAvailable: true};
const preview = {missionId, preview: true, pendingQuestionId: questionId, selectedAgentId: agentId, killAvailable: true};
const noKill = {...live, killAvailable: false};
const noQuestion = {...live, pendingQuestionId: null};
const noMission = {missionId: null, preview: false, killAvailable: true};

cases.resolveStop = resolveCommand(cases.stop, live);
cases.resolveStopPreview = resolveCommand(cases.stop, preview);
cases.resolveStopNoMission = resolveCommand(cases.stop, noMission);
cases.resolveStopAll = resolveCommand(cases.stopAll, preview);
cases.resolveKill = resolveCommand(cases.killId, live);
cases.resolveKillSelected = resolveCommand(cases.killBare, live);
cases.resolveKillMissing = resolveCommand(cases.killBare, {...live, selectedAgentId: null});
cases.resolveKillUnavailable = resolveCommand(cases.killId, noKill);
cases.resolveKillPreview = resolveCommand(cases.killId, preview);
cases.resolveAnswer = resolveCommand(cases.answerText, live);
cases.resolveAnswerNoQuestion = resolveCommand(cases.answerText, noQuestion);
cases.resolveAnswerPreview = resolveCommand(cases.answerText, preview);
cases.resolveUnknown = resolveCommand(cases.unknown, live);

cases.killPresent = killRoutePresent({
  paths: {"/api/missions/{mission_id}/agents/{agent_id}/kill": {post: {}}},
});
cases.killAbsent = killRoutePresent({
  paths: {"/api/missions/{mission_id}/stop": {post: {}}},
});
cases.killGetOnly = killRoutePresent({
  paths: {"/api/missions/{mission_id}/agents/{agent_id}/kill": {get: {}}},
});
cases.killPattern = KILL_ROUTE_PATTERN.test("/api/missions/{mission_id}/agents/{agent_id}/kill");

console.log(JSON.stringify(cases));
