from pathlib import Path

p = Path('index.html')
s = p.read_text()
old = "catch(e){$('court').innerHTML='<option value=\"\">Could not load courts</option>';log('Court lookup failed: '+e.message)}"
new = "catch(e){$('court').innerHTML='<option value=\"\">'+esc(e.message)+'</option>';log('Court lookup failed: '+e.message)}"
if old not in s:
    raise SystemExit('frontend court error block not found')
p.write_text(s.replace(old, new, 1))

p = Path('playlocal_server.py')
s = p.read_text()
old = """        except ApiError as e:
            payload = {'version': 1, 'ok': False, 'error': {'code': e.code, 'message': e.message, 'definitive': e.definitive}}
            status = e.status
"""
new = """        except ApiError as e:
            print(f'API error {e.code}: {e.message}', flush=True)
            payload = {'version': 1, 'ok': False, 'error': {'code': e.code, 'message': e.message, 'definitive': e.definitive}}
            status = e.status
"""
if old not in s:
    raise SystemExit('backend ApiError block not found')
p.write_text(s.replace(old, new, 1))
