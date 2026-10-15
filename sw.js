const C='efc-v1';
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(clients.claim()));
self.addEventListener('fetch',e=>{
  if(e.request.method!='GET')return;
  const u=new URL(e.request.url);
  if(u.origin!=location.origin&&!/^(www\.gstatic\.com|fonts\.googleapis\.com|fonts\.gstatic\.com)$/.test(u.host))return;
  e.respondWith(caches.open(C).then(async c=>{
    const hit=await c.match(e.request);
    const net=fetch(e.request).then(r=>{if(r.ok||r.type=='opaque')c.put(e.request,r.clone());return r}).catch(()=>hit);
    return hit||net;
  }));
});
