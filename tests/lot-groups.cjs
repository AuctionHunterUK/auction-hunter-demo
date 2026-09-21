const { chromium } = require('playwright');
const fs=require('fs'); const path=require('path'); const assert=require('assert/strict');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || undefined,headless:true});
for(const viewport of [{width:1440,height:900},{width:390,height:844}]){
 const context=await browser.newContext({viewport}); const page=await context.newPage(); const requests=[]; const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname.includes('/images/')) requests.push(url.pathname);
  if(url.hostname==='tabs.test'){
   const file=path.join(__dirname,'..',decodeURIComponent(url.pathname));
   if(fs.existsSync(file)&&fs.statSync(file).isFile()) return route.fulfill({path:file});
  }
  return route.abort();
 });
 await page.addInitScript(()=>localStorage.setItem('ah_demo_ok','3b39de0bbf51af9461938056432a535491f2659be786b4b6cd68c828407a1b26'));
 await page.goto('http://tabs.test/finds/index.html'); await page.waitForTimeout(600);
 const imageGroups=await page.evaluate(()=>Object.fromEntries([...document.querySelectorAll('#cards-area section')].map(s=>[s.id,[...s.querySelectorAll('img')].map(i=>new URL(i.dataset.src||i.getAttribute('src'),location.href).pathname)])));
 const visible=()=>page.locator('#cards-area section:visible').evaluateAll(ss=>ss.map(s=>s.id));
 assert.deepEqual(await visible(),['local']); assert(requests.length>0); assert(requests.every(u=>imageGroups.local.includes(u)));
 const localRequests=requests.length;
 await page.locator('[data-target="today"]').click(); await page.waitForTimeout(400); assert.deepEqual(await visible(),['today']);
 assert.equal(await page.locator('#uk-wide img[src]').count(),0);
 await page.locator('[data-target="uk-wide"]').click(); await page.waitForTimeout(400); assert.deepEqual(await visible(),['uk-wide']);
 const loaded=await page.locator('#uk-wide img[src]').count(); assert(loaded>0 && loaded<imageGroups['uk-wide'].length);
 await page.locator('#searchInput').fill('zzzznomatch'); await page.waitForTimeout(150); assert.equal(await page.locator('#uk-wide .card-shell:visible').count(),0); assert(await page.locator('#uk-wide .filter-empty').isVisible());
 await page.locator('[data-target="local"]').click(); assert.deepEqual(await visible(),['local']); assert.equal(await page.locator('#local .card-shell:visible').count(),0);
 await page.locator('#searchInput').fill('pine'); await page.locator('[data-target="today"]').click(); assert((await page.locator('#today .card-shell:visible').count())>0);
 if(viewport.width<=800)await page.locator('.lots-menu-toggle').click();
 await page.locator('#wantedFilterButton').click(); assert.deepEqual(await visible(),['today']);
 await page.locator('[data-target="uk-wide"]').click(); assert.deepEqual(await visible(),['uk-wide']);
 await page.locator('#clearWantedFilter').click(); await page.locator('#searchInput').fill('');
 await page.locator('[data-target="local"]').focus(); await page.keyboard.press('Enter'); assert.deepEqual(await visible(),['local']);
 await page.locator('[data-target="uk-wide"]').click();
 await page.evaluate(()=>{const ca=document.getElementById('cards-area'); ca.scrollTop=ca.scrollHeight; window.scrollTo(0,document.body.scrollHeight)}); await page.waitForTimeout(500);
 assert((await page.locator('#uk-wide img[src]').count())>loaded);
 await page.locator('[data-target="local"]').click();
 assert.equal(await page.locator('#local .card').first().getAttribute('target'),'_blank');
 assert.equal(errors.length,0,errors.join('\n'));

 console.log(JSON.stringify({viewport,localRequests,laterInitiallyLoaded:loaded,laterTotal:imageGroups['uk-wide'].length,errors}));
 await context.close();
}
await browser.close();
})();
