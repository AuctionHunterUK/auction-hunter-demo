const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || undefined,headless:true});
const views=['houses/index.html','finds/index.html','about.html','settings/index.html','proposal.html#overview','proposal.html#proposal'];
for(const scenario of [{w:1571,h:1000},{w:1280,h:900},{w:390,h:844},{w:320,h:740},{w:786,h:500},{w:786,h:700,textZoom:true}]){
const context=await browser.newContext({viewport:{width:scenario.w,height:scenario.h}});
await context.addInitScript(()=>localStorage.setItem('ah_demo_ok','3b39de0bbf51af9461938056432a535491f2659be786b4b6cd68c828407a1b26'));
const page=await context.newPage();await page.route('http://shared.test/**',r=>{
 const file=path.join(__dirname,'..',decodeURIComponent(new URL(r.request().url()).pathname));
 if(fs.existsSync(file)&&fs.statSync(file).isFile())return r.fulfill({path:file}); return r.abort();
});
const metrics=[];
for(const view of views){
await page.goto('http://shared.test/'+view,{waitUntil:'networkidle'});
if(scenario.textZoom){await page.addStyleTag({content:'html {font-size: 200% !important}'});await page.waitForTimeout(250)}
await page.evaluate(()=>document.fonts.ready);
const data=await page.evaluate(()=>{
 const h=document.querySelector('.as-header'); const metric=e=>{let r=e.getBoundingClientRect(),s=getComputedStyle(e);return {x:r.x,y:r.y,w:r.width,h:r.height,font:s.fontSize}};
 const desc=h.querySelector('.as-description');
 return {brand:metric(h.querySelector('.brand')),toggle:metric(h.querySelector('.app-nav')),link:metric(h.querySelector('.app-nav a')),utility:metric(h.querySelector('.as-utilities a')),description:desc?{w:desc.clientWidth,sw:desc.scrollWidth,h:desc.clientHeight,sh:desc.scrollHeight}:null,headerOverflow:h.scrollWidth>h.clientWidth,pageOverflow:document.documentElement.scrollWidth>innerWidth,headerHeight:h.offsetHeight};
});
console.log(JSON.stringify({scenario,view,...data}));if (!((view.startsWith('finds') || view.startsWith('houses')) && scenario.w <= 800)) metrics.push(data);
assert(!data.headerOverflow,view+' header overflow');
if(data.description){assert(data.description.sw<=data.description.w+1);assert(data.description.sh<=data.description.h+1)}
assert(data.link.h>=44);if(!((view.startsWith('finds')||view.startsWith('houses'))&&scenario.w<=800))assert(data.utility.h>=44);
await page.keyboard.press('Tab');await page.locator('.as-header .app-nav a').first().focus();
assert.equal(await page.locator('.as-header .app-nav a').first().evaluate(e=>getComputedStyle(e).outlineStyle),'solid');
if(view.startsWith('finds')){
 await page.locator('[data-target="today"]').click();assert(await page.locator('#today').isVisible());assert(!(await page.locator('#local').isVisible()));
 await page.locator('#searchInput').fill('zznomatch');assert.equal(await page.locator('.card-shell:visible').count(),0);await page.locator('.clear-btn').click();
 if(scenario.w<=800) await page.locator('.lots-menu-toggle').click();
 await page.locator('#wantedFilterButton').click();assert.equal(await page.locator('#wantedFilterButton').getAttribute('aria-pressed'),'true');await page.locator('#clearWantedFilter').click();
 await page.locator('[data-target="local"]').click();
 await page.locator('#featuredSearchesTrigger').click();await page.locator('#featuredSearchesPopover').waitFor({state:'visible'});await page.keyboard.press('Escape');
 assert.equal(await page.locator('.card-shell').count(),583);
}
if(view.startsWith('houses')){
 await page.locator('#chip-soon').focus();await page.keyboard.press('Enter');assert((await page.locator('#chip-soon').getAttribute('class')).includes('on'));
 await page.locator('#chip-all').click();
}
if(view==='proposal.html#overview'){
 await page.getByRole('button',{name:'Now read the detailed proposal →',exact:true}).click();assert(page.url().endsWith('#proposal'));assert(await page.locator('#proposal-text-view').isVisible());await page.waitForFunction(()=>{const h=document.querySelector('.as-header'),t=document.querySelector('.view-switcher');return t.getBoundingClientRect().top>=(getComputedStyle(h).position==='sticky'?h.getBoundingClientRect().bottom:0)-1}, {timeout:5000});
 const tabsTop=await page.locator('.view-switcher').evaluate(e=>e.getBoundingClientRect().top);const headerBottom=await page.locator('.as-header').evaluate(e=>getComputedStyle(e).position==='sticky'?e.getBoundingClientRect().bottom:0);assert(tabsTop>=headerBottom-1, 'proposal switcher obscured');
 await page.getByRole('button',{name:'← Return to the visual overview',exact:true}).click();assert(page.url().endsWith('#overview'));
}
await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));await page.mouse.move(0,0);await page.waitForTimeout(150);

}
const first=metrics[0];for(const m of metrics){assert(Math.abs(m.brand.x-first.brand.x)<1);assert.equal(m.brand.font,first.brand.font);assert(Math.abs(m.toggle.x-first.toggle.x)<1);assert(Math.abs(m.toggle.w-first.toggle.w)<1);assert(Math.abs(m.toggle.h-first.toggle.h)<1);assert(Math.abs(m.brand.y-first.brand.y)<1,'brand y alignment')}
await context.close();
}
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
