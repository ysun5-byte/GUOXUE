import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import {FileBlob, PresentationFile} from '@oai/artifact-tool';

const W='/Users/yuanfeisun/Desktop/八字手环/work/culture-module';
const INPUT='/Users/yuanfeisun/Documents/Codex/2026-10-22/outputs-records-blessed-pitch-r1-handoff/outputs/智道-石墨黑科技版/智道科技_石墨黑科技版_V1.0.pptx';
const C={bg:'#101214',ink:'#F1F1EF',body:'#BDC2C6',muted:'#7F878E',blue:'#8FC7FF',mint:'#79D8B5',line:'#343B43',table:'#171B20',header:'#252D36'};
const FONT='Hiragino Sans GB';
const p=await PresentationFile.importPptx(await FileBlob.load(INPUT));
const sourceIds=['sl/vaxsvy10','sl/y5wne50z','sl/gny5sjyp','sl/14bup87q','sl/zyxsni5k'];
p.slides.keep(sourceIds);
p.slides.reorder(sourceIds);
p.slides.items[0].duplicate().moveTo(4);
const records=(await p.inspect({select:'$.slides[*]',include:['id','index','elements.id','elements.kind','elements.text','elements.position','elements.style']})).records;
const review=await fs.readFile(W+'/content-review.md','utf8');
const noteSections=review.split(/## 第 \d 页/).slice(1,7).map(s=>s.split('**演讲备注／来源：**')[1]?.split('## 制作核对要点')[0].trim()??'');
let added=0;

// Reuse imported editable text objects and master/theme. Each page begins from
// the closest reference composition; unused owned elements are removed.
function page(index){
  const s=p.slides.items[index],r=records[index],used=new Set();
  s.background.fill=C.bg;
  const pool=r.elements.filter(e=>e.kind==='textbox'||(e.kind==='shape'&&e.text));
  function text(name,txt,x,y,w,h,size=28,color=C.body,opts={}){
    const avail=pool.filter(e=>!used.has(e.id));
    let e=opts.sourceId?avail.find(e=>e.id===opts.sourceId):null;
    if(!e&&avail.length){
      e=avail.sort((a,b)=>score(a)-score(b))[0];
      function score(q){const z=q.position;return Math.abs(z.left-x)+Math.abs(z.top-y)+.2*Math.abs(z.width-w);}
    }
    let shape;
    if(e){used.add(e.id);shape=p.resolve(e.id);}
    else shape=s.shapes.add({geometry:'textbox',name:`culture-${++added}-${name}`,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
    shape.position={left:x,top:y,width:w,height:h};
    shape.fill='none';
    shape.line={fill:'none',width:0};
    shape.text=txt;
    shape.text.style={typeface:opts.font??FONT,fontSize:size,bold:opts.bold??false,color,alignment:opts.align??'left',verticalAlignment:'top',autoFit:'none',wrap:'square',lineSpacing:opts.spacing??1.25,insets:0};
    return shape;
  }
  function line(x,y,w,color=C.line){
    return s.shapes.add({geometry:'line',name:`culture-rule-${++added}`,position:{left:x,top:y,width:w,height:0},fill:'none',line:{fill:color,width:1}});
  }
  function chrome(title,sub){
    text('brand','智道',90,45,250,44,25,C.ink,{bold:true});
    text('folio',`文化合作  ·  ${String(index+1).padStart(2,'0')} / 06`,1240,48,274,32,18,C.muted,{align:'right'});
    text('title',title,90,127,1424,105,64,C.ink,{bold:true,spacing:1.12});
    if(sub)text('subtitle',sub,94,248,1420,60,29,C.body);
  }
  function footer(txt){text('footer',txt,90,850,1424,30,17,C.muted,{spacing:1.1});}
  function done(extra=''){
    const remove=r.elements.filter(e=>!used.has(e.id)).map(e=>e.id);
    if(remove.length)p.delete(remove);
    s.speakerNotes.text=noteSections[index]+'\n\n'+extra;
  }
  return {s,text,line,chrome,footer,done};
}

// 01 — source slide 15: three generously spaced editorial rows.
{
  const a=page(0);a.chrome('传统文化保护与科技创新','政策鼓励古籍保护、数字化与文化创新');
  const rows=[
    ['01','古籍保护与研究','整理原典、保存版本，\n建设可检索的文化资料。','2022','古籍工作意见'],
    ['02','影像传播与文创','以音视频和产品设计，\n拓展传统文化的当代表达。','2022','古籍工作意见'],
    ['03','人工智能与体验','探索知识问答、遗产记录\n及文化智能终端应用。','2026','文旅应用试点'],
  ];
  rows.forEach((r,i)=>{const y=350+i*150;
    a.text('number',r[0],90,y,130,92,76,C.blue,{font:'Arial'});
    a.text('theme',r[1],245,y+9,365,65,37,C.ink,{bold:true});
    a.text('body',r[2],655,y+9,565,100,28,C.body,{spacing:1.4});
    a.text('year',r[3],1295,y+8,219,40,25,C.mint,{font:'Arial'});
    a.text('source',r[4],1295,y+49,219,55,20,C.muted);
    if(i<2)a.line(245,y+125,1269);
  });
  a.text('takeaway','智道拟将典籍整理、科学探索与文化体验结合，形成持续的合作项目。',90,807,1424,38,25,C.mint);
  a.footer('依据：2022 年古籍工作意见、2026 年文旅应用试点通知。政策方向不代表项目已获认定或资助。');
  a.done('本模块为独立文化合作材料，沿用主 BP 石墨黑科技版的母版、字体、色彩与版心。政策均按已发布文件引用；不表示正在申报、已获资助或已获官方认可。');
}

// 02 — source slide 18: paired cultural applications and a smaller boundary case.
{
  const a=page(1);a.chrome('文化转化的实践与表达边界','文化资源可以通过研究、数字内容与文创设计进入当代生活');
  a.line(90,345,675);a.line(840,345,674);
  a.text('label','古籍 × 人工智能',90,371,650,40,22,C.blue);
  a.text('case','国家图书馆',90,424,670,68,44,C.ink,{bold:true});
  a.text('detail','古籍智慧平台以大语言模型\n辅助句读、翻译与知识抽取。',90,517,650,110,29,C.body,{spacing:1.5});
  a.text('label','文化 × 沉浸体验',840,371,650,40,22,C.mint);
  a.text('case','逍遥武当',840,424,670,68,44,C.ink,{bold:true});
  a.text('detail','武当文化题材结合 VR 体验、\n文创购物与 AI 摄影。',840,517,650,110,29,C.body,{spacing:1.5});
  a.line(90,660,1424);
  a.text('boundary-label','广告处罚案例',90,693,260,50,28,C.ink,{bold:true});
  a.text('boundary-body','2024 年，北京一企业因风水课程广告含有改变运势等迷信内容，被罚 8 万元。',375,697,1139,80,25,C.body,{spacing:1.35});
  a.text('takeaway','智道围绕文化出处、研究过程与实际功能建立产品价值。',90,795,1424,44,28,C.mint);
  a.footer('来源：文旅部／国家图书馆（2025）、湖北省文旅厅（2025）、北京市市场监管局（2024）。完整出处见备注。');
  a.done('布局中前两例占主要空间，分别说明文化资料整理与体验产品设计的实践。广告处罚案例用于说明宣传边界，不是对宗教或传统文化群体的评价。');
}

// 03 — source slide 16: flat two-column editorial evidence, with dated metric.
{
  const a=page(2);a.chrome('道家文化的当代纪实传播','人物经历与文化现场，已经形成可借鉴的内容表达');
  a.line(90,345,675);a.line(840,345,674);
  a.text('case','武当杰克',90,373,650,65,43,C.ink,{bold:true});
  a.text('metric','100万+',90,455,670,123,94,C.blue,{font:'Arial'});
  a.text('metric-caption','全网粉丝 · 2025 年公开报道口径',94,585,666,40,22,C.muted);
  a.text('body','持续分享习武、音乐与武当生活。\n工作室于 2024 年获湖北正能量\n网络大 V 授牌。',90,658,670,128,27,C.body,{spacing:1.42});
  a.text('case','1667 徽州往事',840,373,674,65,43,C.ink,{bold:true});
  a.text('date','2025.07.14  ·  人物纪录短片',842,457,672,45,23,C.mint);
  a.text('work-title','从军营班长到网红道长？\n白胡子老人出圈背后的故事',840,530,674,105,31,C.ink,{spacing:1.4});
  a.text('body','以齐云山道长的军旅经历\n和日常善行为人物线索，\n把文化放进具体的人与生活。',840,658,674,128,27,C.body,{spacing:1.42});
  a.footer('来源：中国网（2025）、十堰广电（2024）、抖音精选（2025）。粉丝为全网历史口径；1667 案例仅作形式参考，未核实播放量。');
  a.done('本页不用账号流量或公开展示状况推断其所有内容从未被限流或均符合法律、平台规则。完整来源包括中国网（武当融媒供稿）、十堰广电和抖音精选作品页。');
}

// 04 — source slide 17: original hero composition, replaced concept photograph.
{
  const a=page(3);
  a.text('brand','智道',90,45,250,44,25,C.ink,{bold:true});
  a.text('folio','文化合作  ·  04 / 06',1240,48,274,32,18,C.muted,{align:'right'});
  a.text('eyebrow','智道科学探索纪录片  /  前期规划',94,150,730,42,22,C.blue);
  a.text('title','以科学视角\n探索传统文化',90,224,760,195,66,C.ink,{bold:true,spacing:1.22});
  a.text('intro','拟邀请文化传承者与跨学科研究者，\n共同走进古籍、文化现场与当代生活。',94,473,690,112,28,C.body,{spacing:1.5});
  a.text('main','记录发现、分歧与修正',94,641,805,65,37,C.ink,{bold:true});
  a.text('strapline','让研究过程成为故事',94,720,805,50,31,C.mint);
  a.footer('传承者参与解释与判断，研究者带来新的方法。                                      研究场景概念示意 · 非实际拍摄画面');
  const img=a.s.images.add({blob:new Uint8Array(await fs.readFile(W+'/assets/doc-concept.png')),contentType:'image/png',position:{left:0,top:0,width:1600,height:900},fit:'cover',alt:'科学探索纪录片研究场景概念图：古籍、研究者的手和资料分析屏幕。AI 生成，不是实际拍摄画面。'});
  img.sendToBack();
  a.done('本页背景为 image_gen 生成的研究场景概念示意图，不是已组建团队、已开展拍摄或已完成研究的现场照片。完整提示词保存在 work/culture-module/assets/doc-concept.prompt.txt。');
}

// 05 — duplicate of source slide 15: the same three-row grammar as policy page.
{
  const a=page(4);a.chrome('一个问题贯穿一集','让观众跟随同一群人，看到问题如何被提出、研究与修正');
  const rows=[
    ['01','原典与现场','记载从何而来，\n传承者怎样理解？','文献版本\n现场访谈'],
    ['02','研究与检验','哪些问题可用资料比较、\n数据或模型研究？','方法选择\n多方讨论'],
    ['03','发现与修正','证据说明了什么，\n哪些疑问仍待探索？','呈现证据\n保留分歧'],
  ];
  rows.forEach((r,i)=>{const y=350+i*150;
    a.text('number',r[0],90,y,130,92,76,C.blue,{font:'Arial'});
    a.text('step',r[1],245,y+9,365,65,37,C.ink,{bold:true});
    a.text('question',r[2],655,y+9,565,100,28,C.body,{spacing:1.4});
    a.text('method',r[3],1295,y+12,219,90,23,C.mint,{spacing:1.5});
    if(i<2)a.line(245,y+125,1269);
  });
  a.text('takeaway','文化诠释保留语境，可检验命题公开方法与依据。',90,807,1424,40,28,C.mint);
  a.footer('拟采用的单集叙事结构；具体研究方法由选题和可获得证据决定。');
  a.done('建议以一次解释差异、现场观察或研究中的意外发现推动叙事。模型计算、可视化及可运行的原型本身不证明命理判断已获得科学验证。');
}

// 06 — source slide 20: native editable planning table with partner participation.
{
  const a=page(5);a.chrome('科学探索纪录片前期计划','从首期选题与样片出发，逐步确定系列内容与发行安排');
  const values=[
    ['阶段','拟交付','合作方参与'],
    ['01  选题调研','首期问题、人物与资料范围','共选主题，确认资料出处'],
    ['02  访谈与试拍','访谈档案、现场影像与授权清单','参与讲述，核对文化背景'],
    ['03  样片制作','一支 3—5 分钟样片','审看素材，讨论叙事表达'],
    ['04  系列评估','后续集数、预算与发行建议','明确署名与成果使用安排'],
  ];
  const t=a.s.tables.add({rows:5,columns:3,left:90,top:350,width:1424,height:420,columnWidths:[340,580,504],values});
  t.frame={left:90,top:350,width:1424,height:420};
  t.styleOptions={headerRow:false,bandedRows:false};
  t.borders.assign({fill:C.line,width:.8,style:'solid'});
  t.cells.block({row:0,column:0,rowCount:5,columnCount:3}).assign({margins:{left:24,right:18,top:10,bottom:10}});
  for(let r=0;r<5;r++){
    t.rows[r].height=r===0?64:89;
    for(let c=0;c<3;c++){
      const cell=t.getCell(r,c);
      cell.fill=r===0?C.header:C.table;
      cell.text.style={typeface:FONT,fontSize:r===0?25:26,bold:r===0||c===0,color:r===0?C.ink:c===0?C.blue:C.body,verticalAlignment:'middle',autoFit:'none',wrap:'square',lineSpacing:1.18,insets:0};
    }
  }
  a.text('takeaway','首期形成可讨论的样片，并向合作方交付约定的整理成果。',90,806,1424,42,28,C.mint);
  a.footer('前期拟议计划；时间、人员与预算另行落实。具体拍摄、资料及公开传播授权按内容确认。');
  a.done('推进计划以样片为首期可审阅成果，不承诺未确认的电视台、导演、机构或平台合作。所有交付和时长均为拟议方案。');
}

await fs.mkdir(W+'/draft-render',{recursive:true});
const content=await p.inspect({select:'$.slides[*]',include:['id','index','elements.id','elements.kind','elements.text','elements.position','notes.text']});
await fs.writeFile(W+'/content.json',JSON.stringify(content.records,null,2));
await fs.writeFile(W+'/module.proto.json',JSON.stringify(p.toProto()));
for(let i=0;i<p.slides.items.length;i++){
  const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});
  await fs.writeFile(W+`/draft-render/slide-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));
  const l=await p.slides.items[i].export({format:'layout'});
  await fs.writeFile(W+`/draft-render/slide-${i+1}.layout.json`,await l.text());
}
await(await PresentationFile.exportPptx(p)).save(W+'/candidate.pptx');
const hash=crypto.createHash('sha256').update(await fs.readFile(INPUT)).digest('hex');
await fs.writeFile(W+'/source.sha256',hash+'\n');
console.log(JSON.stringify({slides:p.slides.items.length,candidate:W+'/candidate.pptx',sourceSha256:hash}));
