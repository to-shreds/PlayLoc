from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import hashlib, json, os, re, secrets, threading, time, requests

BASE='https://www.playlocal.com'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
SESSIONS={}; IDEM={}; LOCK=threading.RLock()

class ApiError(Exception):
    def __init__(self, code, message, status=400, definitive=False):
        self.code=code; self.message=message; self.status=status; self.definitive=definitive
        super().__init__(message)

def soup(text): return BeautifulSoup(text,'html.parser')
def clean(text): return re.sub(r'\s+',' ',text or '').strip()

def browser_session():
    s=requests.Session()
    s.headers.update({
        'User-Agent':UA,
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language':'en-US,en;q=0.9',
        'Cache-Control':'no-cache',
        'Pragma':'no-cache',
        'Upgrade-Insecure-Requests':'1',
    })
    return s

def get_page(sess,url,params=None,referer=None,timeout=25):
    headers={'Referer':referer} if referer else None
    r=sess.get(url,params=params,headers=headers,timeout=timeout,allow_redirects=True)
    if r.status_code==403:
        raise ApiError('PLAYLOCAL_FORBIDDEN','PlayLocal refused the hosted request (HTTP 403). CourtFlow is using a normal browser session, but PlayLocal is not accepting this server request.',502,False)
    r.raise_for_status()
    return r

def form_data(form):
    out=[]
    for el in form.find_all(['input','select','textarea']):
        name=el.get('name'); typ=(el.get('type') or '').lower()
        if not name or el.has_attr('disabled') or typ in ('submit','button','image','reset','file'): continue
        if typ in ('checkbox','radio') and not el.has_attr('checked'): continue
        if el.name=='select':
            selected=el.find_all('option',selected=True) or ([el.find('option')] if el.find('option') else [])
            out.extend((name,o.get('value','')) for o in selected)
        else: out.append((name,el.get('value','')))
    return out

def submit(sess,page,form,overrides=None):
    data=form_data(form)
    for k,v in (overrides or {}).items(): data=[(a,b) for a,b in data if a!=k]+[(k,str(v))]
    btn=form.find(['button','input'],attrs={'type':'submit'})
    if btn and btn.get('name'): data.append((btn['name'],btn.get('value') or clean(btn.text)))
    method=(form.get('method') or 'post').lower(); url=urljoin(page.url,form.get('action') or page.url)
    r=sess.request(method,url,data=data if method!='get' else None,params=data if method=='get' else None,headers={'Referer':page.url},timeout=25,allow_redirects=True)
    if r.status_code==403:
        raise ApiError('PLAYLOCAL_FORBIDDEN','PlayLocal refused the hosted request (HTTP 403).',502,False)
    r.raise_for_status()
    return r

def login(account_id,username,password):
    s=browser_session()
    try: get_page(s,BASE+'/',referer=BASE+'/')
    except Exception: pass
    p=get_page(s,BASE+'/sign_in',referer=BASE+'/')
    d=soup(p.text)
    form=next((f for f in d.find_all('form') if f.find('input',{'type':'password'})),None)
    if not form: raise ApiError('UPSTREAM_CHANGED','Could not find PlayLocal sign-in form.',502)
    user=form.find('input',{'type':'email'}) or form.find('input',attrs={'name':re.compile('email',re.I)})
    pw=form.find('input',{'type':'password'})
    if not user or not pw: raise ApiError('UPSTREAM_CHANGED','Could not identify PlayLocal sign-in fields.',502)
    r=submit(s,p,form,{user.get('name'):username,pw.get('name'):password})
    if urlparse(r.url).path=='/sign_in' and soup(r.text).find('input',{'type':'password'}):
        raise ApiError('AUTH_REJECTED','PlayLocal rejected that email/password.',401,True)
    token=secrets.token_urlsafe(32); identity=hashlib.sha256(username.strip().lower().encode()).hexdigest()[:32]
    with LOCK: SESSIONS[token]={'accountId':account_id,'identity':identity,'session':s,'created':time.time()}
    return {'sessionToken':token,'identity':identity}

def session(token,account_id):
    with LOCK: item=SESSIONS.get(token)
    if not item or item['accountId']!=account_id: raise ApiError('AUTH_REJECTED','PlayLocal session expired. Sign in again.',401,True)
    return item['session']

def search_pages(q,sess=None):
    start=int(q.get('start',960)); end=int(q.get('end',1320)); parts=[]
    for name,a,b in [('early_morning',0,480),('morning',480,720),('afternoon',720,960),('evening',960,1200),('night',1200,1440)]:
        if start<b and end>a: parts.append(name)
    s=sess or browser_session()
    get_page(s,BASE+'/facilities',referer=BASE+'/')
    pages=[]
    for part in parts or ['evening']:
        params={'search[date]':q.get('date',''),'search[location]':q.get('location',''),'search[sport]':q.get('sport','tennis'),'search[time]':part,'commit':'Find Courts'}
        pages.append(get_page(s,BASE+'/facilities',params=params,referer=BASE+'/facilities'))
    return pages

def availability(q,sess=None):
    wanted=str(q.get('facilityId') or ''); start=int(q.get('start',0)); end=int(q.get('end',1440)); facilities={}; slots={}
    for page in search_pages(q,sess):
        d=soup(page.text)
        for link in d.find_all('a',href=re.compile(r'/facilities/[^/]+/reservations/new')):
            m=re.search(r'/facilities/([^/]+)/reservations/new',link.get('href',''))
            if not m: continue
            fid=m.group(1)
            if wanted and fid!=wanted: continue
            box=link.find_parent(['li','article','section']) or link.parent; text=clean(box.get_text(' ',strip=True))
            heading=box.find(['h1','h2','h3','h4','h5','strong']); name=clean(heading.get_text(' ',strip=True)) if heading else 'Facility '+fid
            price_match=re.search(r'\$(\d+(?:\.\d{1,2})?)',text); price=int(round(float(price_match.group(1))*100)) if price_match else 0
            court_match=re.search(r'(\d+)\s+courts?\s*\((\d+)\s+reservable',text,re.I); count=int(court_match.group(2)) if court_match else 1
            courts=[{'id':f'{fid}:court:{i}','name':f'Court {i}'} for i in range(1,max(1,count)+1)]
            facilities[fid]={'id':fid,'name':name,'courts':courts}
            for node in box.find_all(['li','div','span','p','td','a','button']):
                txt=clean(node.get_text(' ',strip=True)); mt=re.fullmatch(r'(\d{1,2})(?::00)?\s*(am|pm)(?:\s+(Not Available|Unavailable|Closed|Full|Booked))?',txt,re.I)
                if not mt: continue
                h=int(mt.group(1))%12+(12 if mt.group(2).lower()=='pm' else 0); st=h*60
                if st<start or st>=end: continue
                avail=not bool(mt.group(3))
                for c in courts:
                    key=(fid,c['id'],st); row={'slotId':f'{fid}:{c["id"]}:{q.get("date")}:{st}','facilityId':fid,'facilityName':name,'courtId':c['id'],'courtName':c['name'],'date':q.get('date'),'start':st,'end':st+60,'available':avail,'priceCents':price}
                    if key not in slots or avail: slots[key]=row
    return {'coverage':'complete','slotMinutes':60,'asOf':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'facilities':list(facilities.values()),'slots':list(slots.values())}

def reservation_block(link):
    box=link.find_parent(['li','article','tr','section'])
    if box: return box
    cur=link.parent
    for _ in range(5):
        if cur is None: break
        txt=clean(cur.get_text(' ',strip=True))
        if 20<=len(txt)<=1200: return cur
        cur=cur.parent
    return link.parent

def history(req):
    s=session(req['sessionToken'],req['accountId'])
    p=get_page(s,BASE+'/user/reservations',referer=BASE+'/')
    if urlparse(p.url).path=='/sign_in': raise ApiError('AUTH_REJECTED','PlayLocal session expired.',401,True)
    d=soup(p.text); rows=[]; seen=set()
    for link in d.find_all('a',href=re.compile(r'/reservations/\d+')):
        href=link.get('href','')
        m=re.search(r'/reservations/(\d+)',href)
        if not m or m.group(1) in seen: continue
        rid=m.group(1); seen.add(rid); box=reservation_block(link); text=clean(box.get_text(' ',strip=True)) if box else clean(link.get_text(' ',strip=True))
        heading=box.find(['h1','h2','h3','h4','h5','strong']) if box else None
        title=clean(heading.get_text(' ',strip=True)) if heading else clean(link.get_text(' ',strip=True)) or f'Reservation {rid}'
        date_match=re.search(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?',text,re.I) or re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',text)
        times=re.findall(r'\b\d{1,2}(?::\d{2})?\s*(?:AM|PM)\b',text,re.I)
        low=text.lower(); status='current'
        for candidate in ('cancelled','canceled','completed','confirmed','upcoming'):
            if candidate in low: status='cancelled' if candidate=='canceled' else candidate; break
        rows.append({'id':rid,'title':title,'date':date_match.group(0) if date_match else '', 'start':times[0] if times else '', 'end':times[1] if len(times)>1 else '', 'status':status,'detailsUrl':urljoin(BASE,href),'text':text[:1000]})
    return {'accountId':req['accountId'],'reservations':rows,'count':len(rows),'sourceUrl':p.url,'pageTitle':clean(d.title.get_text(' ',strip=True)) if d.title else ''}

def set_fields(form,slot):
    out={}; hour=slot['start']//60; num=re.search(r'(\d+)$',slot.get('courtName',''))
    for el in form.find_all(['input','select','textarea']):
        name=el.get('name'); typ=(el.get('type') or '').lower()
        if not name or el.has_attr('disabled'): continue
        desc=' '.join(filter(None,[name,el.get('id'),el.get('aria-label')])).lower()
        if re.search(r'date|day',desc) and typ not in ('checkbox','radio'): out[name]=slot['date']
        elif re.search(r'time|hour|start|slot',desc):
            if el.name=='select':
                pattern=rf'\b{hour%12 or 12}(?::00)?\s*{"pm" if hour>=12 else "am"}\b'; option=next((x for x in el.find_all('option') if re.search(pattern,clean(x.text)+' '+x.get('value',''),re.I)),None)
                if option: out[name]=option.get('value','')
            elif typ not in ('checkbox','radio'): out[name]=f'{hour%12 or 12}:00 {"PM" if hour>=12 else "AM"}'
        elif 'court' in desc and el.name=='select':
            opts=[x for x in el.find_all('option') if x.get('value') and not x.has_attr('disabled')]; option=None
            if num: option=next((x for x in opts if re.search(rf'\bCourt\s*{num.group(1)}\b',clean(x.text),re.I)),None)
            if option is None and opts: option=opts[0]
            if option: out[name]=option.get('value','')
        elif typ=='checkbox' and (el.has_attr('required') or re.search(r'term|policy|agree|accept',desc)): out[name]=el.get('value') or '1'
    return out

def book(req):
    key=req['idempotencyKey']
    with LOCK:
        if key in IDEM: return IDEM[key]
    s=session(req['sessionToken'],req['accountId']); slot=req['slot']
    snap=availability({'date':slot['date'],'sport':'tennis','start':slot['start'],'end':slot['end'],'facilityId':slot['facilityId']},s)
    if not any(x['available'] and x['start']==slot['start'] and x['courtId']==slot['courtId'] for x in snap['slots']): raise ApiError('SLOT_UNAVAILABLE','PlayLocal no longer shows that slot as available.',409,True)
    p=get_page(s,f"{BASE}/facilities/{slot['facilityId']}/reservations/new?sport=tennis",referer=BASE+'/facilities')
    if urlparse(p.url).path=='/sign_in': raise ApiError('AUTH_REJECTED','PlayLocal session expired.',401,True)
    d=soup(p.text); form=next((f for f in d.find_all('form') if re.search(r'reservation|booking',(f.get('action') or '')+' '+clean(f.get_text(' ',strip=True)),re.I)),None)
    if not form: raise ApiError('UPSTREAM_CHANGED','PlayLocal reservation form was not found.',502)
    prices=[int(round(float(x)*100)) for x in re.findall(r'\$(\d+(?:\.\d{1,2})?)',clean(d.get_text(' ',strip=True)))]; detected=max(prices) if prices else 0
    if detected>0: raise ApiError('INTERACTIVE_REQUIRED','This reservation has a charge; automatic paid booking is not enabled.',409,True)
    r=submit(s,p,form,set_fields(form,slot)); body=clean(soup(r.text).get_text(' ',strip=True))
    if re.search(r'error|unable|failed|not available|already (?:reserved|booked)',body,re.I): raise ApiError('BOOKING_REJECTED',body[:300],409,True)
    m=re.search(r'/reservations/(\d+)',urlparse(r.url).path)
    if not (m or re.search(r'reservation (?:confirmed|created|booked)|successfully reserved|confirmation',body,re.I)):
        raise ApiError('UNKNOWN_OUTCOME','PlayLocal responded, but CourtFlow could not prove that the reservation was created.',502)
    result={'id':m.group(1) if m else 'playlocal-'+key[:12],**slot,'accountId':req['accountId'],'status':'confirmed','idempotencyKey':key}
    with LOCK: IDEM[key]=result
    return result

def dispatch(req):
    if req.get('version')!=1: raise ApiError('VERSION','CourtFlow protocol version 1 is required.')
    action=req.get('action')
    if action=='capabilities': return {'vendor':'playlocal','idempotency':True,'history':True,'completeDailyHistory':False,'slotMinutes':60}
    if action=='authenticate': return login(req['accountId'],req['username'],req['password'])
    if action=='availability':
        s=None
        if req.get('sessionToken') and req.get('accountId'): s=session(req['sessionToken'],req['accountId'])
        return availability(req.get('query') or {},s)
    if action=='history': return history(req)
    if action=='book': return book(req)
    raise ApiError('ACTION','Unknown adapter action.')

class Handler(SimpleHTTPRequestHandler):
    def cors(self):
        origin=self.headers.get('Origin',''); allowed=os.environ.get('COURTFLOW_ALLOWED_ORIGIN','*')
        if allowed=='*' or origin==allowed: self.send_header('Access-Control-Allow-Origin','*' if allowed=='*' else origin)
        self.send_header('Vary','Origin'); self.send_header('Access-Control-Allow-Headers','Content-Type, Authorization'); self.send_header('Access-Control-Allow-Methods','POST, OPTIONS, GET')
    def do_OPTIONS(self): self.send_response(204); self.cors(); self.send_header('Content-Length','0'); self.end_headers()
    def do_GET(self):
        if self.path=='/' or self.path=='/health':
            raw=b'CourtFlow PlayLocal adapter'; self.send_response(200); self.send_header('Content-Type','text/plain'); self.cors(); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
            return
        if self.path=='/upstream':
            try:
                s=browser_session(); r=get_page(s,BASE+'/facilities',referer=BASE+'/'); payload={'ok':True,'status':r.status_code,'url':r.url,'title':clean(soup(r.text).title.get_text(' ',strip=True)) if soup(r.text).title else ''}; status=200
            except ApiError as e: payload={'ok':False,'code':e.code,'message':e.message}; status=e.status
            except requests.RequestException as e: payload={'ok':False,'code':'PLAYLOCAL_CONNECTION','message':str(e)}; status=502
            raw=json.dumps(payload).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.cors(); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_error(404)
    def do_POST(self):
        if self.path!='/adapter': return self.send_error(404)
        try:
            n=int(self.headers.get('Content-Length','0')); req=json.loads(self.rfile.read(n) or b'{}'); payload={'version':1,'ok':True,'data':dispatch(req)}; status=200
        except ApiError as e: payload={'version':1,'ok':False,'error':{'code':e.code,'message':e.message,'definitive':e.definitive}}; status=e.status
        except requests.RequestException as e: payload={'version':1,'ok':False,'error':{'code':'PLAYLOCAL_CONNECTION','message':'Could not reach PlayLocal: '+str(e),'definitive':False}}; status=502
        except Exception as e: payload={'version':1,'ok':False,'error':{'code':'CONNECTOR_ERROR','message':str(e),'definitive':False}}; status=500
        raw=json.dumps(payload).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.cors(); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)

if __name__=='__main__':
    port=int(os.environ.get('PORT','8765')); host=os.environ.get('HOST','0.0.0.0')
    print(f'CourtFlow adapter listening on {host}:{port}')
    ThreadingHTTPServer((host,port),Handler).serve_forever()
