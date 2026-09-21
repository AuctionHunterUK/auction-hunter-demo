const {chromium}=require('playwright');
const path=require('path'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||undefined,headless:true});
 for(const width of [1571,390,320]){
  const page=await browser.newPage({viewport:{width,height:844}});
  await page.clock.install({time:new Date('2026-09-21T12:00:00Z')});
  await page.addInitScript(()=>localStorage.setItem('ah_demo_ok','3b39de0bbf51af9461938056432a535491f2659be786b4b6cd68c828407a1b26'));
  await page.route('http://map.test/**',r=>{
   const file=path.join(__dirname,'..',new URL(r.request().url()).pathname);
   return fs.existsSync(file)&&fs.statSync(file).isFile()?r.fulfill({path:file}):r.abort();
  });
  await page.goto('http://map.test/houses/index.html',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.querySelector('#chip-urgent').getAttribute('aria-pressed')==='true');
  // Isolated in-memory boundary fixtures, never modify the saved catalogue.
  await page.evaluate(()=>{
   allH.forEach(h=>h.sales=[]);
   const dates=['2026-09-20','2026-09-21','2026-09-24','2026-09-25','2026-10-05','2026-10-06'];
   const houses=allH.filter(h=>h.lat&&!h.url.includes('the-saleroom')).slice(0,dates.length);
   houses.forEach((h,i)=>h.sales=[{date:dates[i],title:'Timing test',time:''}]);
   resetAll();
  });
  const geometry=()=>page.evaluate(()=>({scroll:scrollY,center:map.getCenter(),zoom:map.getZoom(),toolbar:document.querySelector('#toolbar').getBoundingClientRect().toJSON()}));
  const before=await geometry();
  for(const input of ['click','Enter','Space']){
   for(const mode of ['urgent','urgent','soon','soon','2wk','2wk','all','all','urgent']){
    const button=page.locator('#chip-'+mode);
    if(input==='click')await button.click();else{await button.focus();await page.keyboard.press(input)}
    const result=await page.evaluate(()=>({active:activeChip,ids:[...document.querySelectorAll('#sblist .si')].map(e=>+e.dataset.id).sort((a,b)=>a-b),pins:Object.entries(markers).filter(([,m])=>map.hasLayer(m)).map(([id])=>+id).sort((a,b)=>a-b),pressed:document.querySelectorAll('#toolbar [aria-pressed="true"]').length}));
    assert.equal(result.active,mode);assert.equal(result.pressed,1);assert.deepEqual(result.ids,result.pins);
    if(mode!=='all')assert.equal(result.ids.length,{urgent:2,soon:4,'2wk':5}[mode]);else assert(result.ids.length>5);
    assert.deepEqual(await geometry(),before,'Filter changed page/map geometry');
   }
  }
  // Repeated selection must retain the user's sidebar position and nodes.
  await page.locator('#chip-2wk').click();
  await page.evaluate(()=>window.firstResult=document.querySelector('#sblist .si'));
  await page.locator('#chip-2wk').click();assert(await page.evaluate(()=>window.firstResult===document.querySelector('#sblist .si')));
  if(width<=800)assert.equal(await page.locator('.as-bottom').evaluate(e=>e.firstElementChild.className),'as-utilities');
  console.log(`PASS ${width}px: timing boundaries, repeated clicks/Enter/Space, All, marker/list agreement, stable page/map geometry`);
  await page.close();
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
