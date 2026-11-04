import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const INPUT='/Users/yuanfeisun/Documents/Codex/2026-10-22/outputs-records-blessed-pitch-r1-handoff/outputs/智道-石墨黑科技版/智道科技_石墨黑科技版_V1.0.pptx';
const DIR='/Users/yuanfeisun/Desktop/八字手环/work/culture-module/reference';
const p=await PresentationFile.importPptx(await FileBlob.load(INPUT));
const scan=await p.inspect({select:'$.slides[*]',include:['id','index','elements.id','elements.kind','elements.text','elements.position','elements.style','notes.text']});
await fs.writeFile(DIR+'/source.ndjson',scan.ndjson);
await fs.writeFile(DIR+'/source.json',JSON.stringify(scan.records,null,2));
const lay=await p.inspect({kind:'layout',maxChars:10000});
await fs.writeFile(DIR+'/layouts.txt',lay.ndjson);
console.log('MASTERS',p.masters.items.map(m=>({id:m.id,name:m.name})));
console.log('PLACEHOLDERS',p.slides.items[14].placeholders.items.map(x=>({id:x.id,name:x.name})));
for (const i of [14,16,17]) {
 const b=await p.export({slide:p.slides.items[i],format:'png',scale:.75});
 await fs.writeFile(DIR+`/slide-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));
}
await fs.writeFile(DIR+'/reference.proto.json',JSON.stringify(p.toProto()));
console.log('reference inspected',scan.recordCount);
