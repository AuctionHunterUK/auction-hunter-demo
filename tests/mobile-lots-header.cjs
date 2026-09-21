const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||undefined,headless:true});
const page=await browser.newPage();
await page.addInitScript(()=>localStorage.setItem('ah_demo_ok','3b39de0bbf51af9461938056432a535491f2659be786b4b6cd68c828407a1b26'));
await page.route('http://lots.test/**',r=>{const f=path.join(__dirname,'..',new URL(r.request().url()).pathname);return fs.existsSync(f)&&fs.statSync(f).isFile()?r.fulfill({path:f}):r.abort()});
for(const width of [390,320,1571,390]){
 await page.setViewportSize({width,height:844});await page.goto('http://lots.test/finds/index.html',{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);
 assert.equal(await page.locator('.card-shell').count(),583);
 const mobile=width<=800;
 assert.equal(await page.locator('.lots-menu-toggle').isVisible(),mobile);
 if(mobile){
  assert(!(await page.locator('.as-utilities').isVisible()));
  const metrics=await page.evaluate(()=>({height:document.querySelector('.as-header').offsetHeight,overflow:document.documentElement.scrollWidth>innerWidth,groups:[...document.querySelectorAll('.group-tab')].map(e=>({y:e.getBoundingClientRect().y,h:e.getBoundingClientRect().height})),imageTop:[...document.querySelectorAll('.card-shell img')].find(e=>e.getBoundingClientRect().width).getBoundingClientRect().top}));
  console.log(width,JSON.stringify(metrics));assert(metrics.height<190);assert(!metrics.overflow);assert(metrics.groups.every(g=>g.y===metrics.groups[0].y&&g.h>=44));
  if(process.env.CAPTURE_DIR)await page.screenshot({path:path.join(process.env.CAPTURE_DIR,`preview-mobile-lots-${width}-collapsed.png`)});
 }
 await page.locator('[data-target="today"]').click();assert(await page.locator('#today').isVisible());
 await page.locator('[data-target="uk-wide"]').focus();await page.keyboard.press('Enter');assert(await page.locator('#uk-wide').isVisible());
 await page.locator('#searchInput').fill('zznomatch');assert.equal(await page.locator('.card-shell:visible').count(),0);await page.locator('.clear-btn').click();
 await page.locator('[data-target="local"]').click();
 if(mobile){await page.locator('.lots-menu-toggle').focus();await page.keyboard.press('Enter');assert(await page.locator('.as-utilities').isVisible());}
 await page.locator('#featuredSearchesTrigger').click();await page.locator('#featuredSearchesPopover').waitFor({state:'visible'});
 if(mobile&&process.env.CAPTURE_DIR)await page.screenshot({path:path.join(process.env.CAPTURE_DIR,`preview-mobile-lots-${width}-expanded.png`)});
 if(!mobile){await page.locator('#featuredSearchesTrigger').press('Escape');await page.mouse.move(0,0);await page.locator('#wantedFilterButton').focus();}
 await page.locator('#wantedFilterButton').click();assert.equal(await page.locator('#wantedFilterButton').getAttribute('aria-pressed'),'true');
 if(mobile){
  await page.locator('#wantedFilterButton').focus();await page.keyboard.press('Escape');assert.equal(await page.locator('.lots-menu-toggle').getAttribute('aria-expanded'),'false');assert.equal(await page.locator('.lots-menu-toggle').getAttribute('aria-label'),'Menu, refined search on');assert(await page.locator('.lots-menu-toggle').evaluate(e=>e===document.activeElement));
  await page.locator('.lots-menu-toggle').click();await page.locator('#wantedFilterButton').click();await page.locator('.lots-menu-toggle').click();
  await page.setViewportSize({width:1571,height:844});await page.locator('#featuredSearchesTrigger').waitFor({state:'visible'});assert(await page.locator('#wantedFilterButton').isVisible());assert(await page.locator('.as-utilities').isVisible());
 }else if(process.env.CAPTURE_DIR)await page.screenshot({path:path.join(process.env.CAPTURE_DIR,'preview-lots-desktop.png')});
}
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
