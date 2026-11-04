import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {finalizePresentation} from '/Users/yuanfeisun/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations/container_tools/artifact_tool_utils.mjs';
const ROOT='/Users/yuanfeisun/Desktop/八字手环';
const W=ROOT+'/work/culture-module';
const SKILL='/Users/yuanfeisun/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const INPUT='/Users/yuanfeisun/Documents/Codex/2026-10-22/outputs-records-blessed-pitch-r1-handoff/outputs/智道-石墨黑科技版/智道科技_石墨黑科技版_V1.0.pptx';
const referenceSha256=(await fs.readFile(W+'/source.sha256','utf8')).trim();
const afterHash=crypto.createHash('sha256').update(await fs.readFile(INPUT)).digest('hex');
if(afterHash!==referenceSha256)throw Error('Source changed');
process.env.RUNTIME_NODE_MODULES='/Users/yuanfeisun/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const result=await finalizePresentation({
  workspaceDir:ROOT,
  candidatePath:W+'/candidate.pptx',
  finalPath:ROOT+'/output/文化合作与科学探索纪录片/智道_文化合作与科学探索纪录片_石墨黑版_V1.0.pptx',
  explicitTotalSlideCount:6,
  requiredNativeTableOwnerSlides:[6],
  requiredNativeChartOwnerSlides:[],
  pythonExecutable:'/Users/yuanfeisun/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
  integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',
  layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',
  layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','6'],
  fontPolicy:{basis:'reference',families:['Hiragino Sans GB','Arial'],referencePath:INPUT,referenceSha256},
  verifyArtifactToolImport:true,
  receiptPath:W+'/validation.json'
});
console.log(JSON.stringify({final:result.finalPath,sha:result.finalSha256,layout:result.presentationLayout}));
