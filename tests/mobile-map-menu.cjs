const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||undefined,headless:true});
const page=await browser.newPage();await page.addInitScript(()=>localStorage.setItem('ah_demo_ok','3b39de0bbf51af9461938056432a535491f2659be786b4b6cd68c828407a1b26'));
await page.route('http://menu.test/**',r=>{const f=path.join(__dirname,'..',new URL(r.request().url()).pathname);return fs.existsSync(f)&&fs.statSync(f).isFile()?r.fulfill({path:f}):r.abort()});
for(const width of [320,390,800,1571]){
 await page.setViewportSize({width,height:844});await page.goto('http://menu.test/finds/index.html',{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);
 const lots=await page.locator('.lots-menu-toggle').boundingBox();
 await page.goto('http://menu.test/houses/index.html',{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);
 const menu=page.locator('.lots-menu-toggle');
 if(width<=800){
  assert.deepEqual(await menu.boundingBox(),lots,'Menu position differs from Lots');
  assert(!(await page.locator('.as-utilities').isVisible()));assert(!(await page.locator('.snapshot-label').isVisible()));
  assert(await page.locator('.as-description').isVisible());assert(await page.locator('#toolbar').isVisible());
  const metrics=await page.evaluate(()=>({height:document.querySelector('.as-header').offsetHeight,overflow:document.documentElement.scrollWidth>innerWidth}));assert(!metrics.overflow);console.log(width,metrics);
  if(process.env.CAPTURE_DIR&&width<800)await page.screenshot({path:path.join(process.env.CAPTURE_DIR,`preview-mobile-map-${width}-collapsed.png`)});
  await menu.focus();await page.keyboard.press('Enter');assert.equal(await menu.getAttribute('aria-expanded'),'true');
  assert(await page.locator('.snapshot-label').isVisible());
  assert.deepEqual(await page.locator('#map-mobile-options .as-utilities a').evaluateAll(es=>es.map(e=>[e.textContent,e.getAttribute('href')])),[['About','../about.html'],['Edit','../settings/'],['Private Proposal','../proposal.html']]);
  await page.locator('#map-mobile-options a').first().focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Edit');
  if(process.env.CAPTURE_DIR&&width<800)await page.screenshot({path:path.join(process.env.CAPTURE_DIR,`preview-mobile-map-${width}-expanded.png`)});
  await page.keyboard.press('Escape');assert.equal(await menu.getAttribute('aria-expanded'),'false');assert(await menu.evaluate(e=>e===document.activeElement));
  await menu.click();await menu.click();assert(!(await page.locator('.as-utilities').isVisible()));
  await page.setViewportSize({width:1571,height:844});await page.locator('.as-utilities').waitFor({state:'visible'});assert(await page.locator('.snapshot-label').isVisible());assert(!(await menu.isVisible()));
 }else{assert(!(await menu.isVisible()));assert(await page.locator('.as-utilities').isVisible());}
}
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
