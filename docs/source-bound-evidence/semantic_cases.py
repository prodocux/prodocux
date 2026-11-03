"""Product-neutral executable contract examples; no runtime execution."""
import copy
import json
import semantic_validator as v
ROOT=v.ROOT
E='urn:pdx:draft:er003:support:2'
K='urn:pdx:draft:cr003:core:1'
CE='urn:pdx:draft:er003:core:1'
H=v.sha(b'synthetic-fixture')
count=0
results=[]

def check(name,fn,expected='ok'):
    global count
    try:
        out=fn(); actual='ok' if out is None else out
    except v.Invalid as exc: actual=exc.code
    assert actual==expected,(name,actual,expected)
    count+=1;results.append({'name':name,'expected':expected,'actual':actual})


def sample(s,base):
    if '$ref' in s:
        uri,_,fragment=s['$ref'].partition('#')
        doc=v.SCHEMAS[uri] if uri else v.SCHEMAS[base]
        for key in fragment.strip('/').split('/') if fragment else []: doc=doc[key]
        return sample(doc,uri or base)
    if 'const' in s:return s['const']
    if 'enum' in s:return s['enum'][0]
    if 'oneOf' in s:return sample(s['oneOf'][0],base)
    t=s.get('type');t=t[0] if isinstance(t,list) else t
    if t=='object':return {k:sample(s['properties'][k],base) for k in s.get('required',[])}
    if t=='array':
        values=[sample(s['items'],base) for _ in range(s.get('minItems',0))]
        if s.get('uniqueItems'):values=[x+str(i) if isinstance(x,str) else x for i,x in enumerate(values)]
        return values
    if t=='boolean':return False
    if t=='integer':return s.get('minimum',0)
    if t=='null':return None
    if t=='string':
        if s.get('format')=='date-time':return '2026-11-03T00:00:00Z'
        if s.get('pattern','').startswith('^[A-Z][A-Z0-9_'):return 'SAFE_ERROR'
        if '[a-f0-9]' in s.get('pattern',''):return H
        if s.get('pattern','').startswith('^-?'):return '0'
        if 'artifact://' in s.get('pattern',''):return 'artifact://example/evidence.json'
        if 'workspace://' in s.get('pattern',''):return 'workspace://example/root'
        return 'example-001' + 'x'*max(0,s.get('minLength',0)-11)
    raise AssertionError(('unsupported schema sample',s))


def artifact():
    return {'schema_version':'prodocux_opaque_artifact_v1','artifact_id':'artifact-001',
            'uri':'artifact://example/evidence.json','sha256':v.sha(b'evidence'),
            'size_bytes':8,'media_type':'application/json'}


def kernel_cases():
    request=copy.deepcopy(json.loads((ROOT/'examples.json').read_text())['bases']['kernel_request'])
    text='Subtotal: 900.00\nAmount due: 1100.00\n'
    context={'source_sha256':request['source']['sha256'],'parser_contract':request['parser_contract'],
             'page_number':1,'total_pages':55,'text':text,'quality':'complete_native_text'}
    check('K01 exact',lambda:v.kernel_result(request,context)['overall_status'],'pass')
    def changed(name,path,value,expected):
        obj=copy.deepcopy(request);target=obj
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value
        def run():return v.kernel_result(obj,context)['checks'][0]['reason_code']
        check(name,run,expected)
    changed('K02 invented quote',['checks',0,'quote'],'Amount due: 900.00','QUOTE_MISMATCH')
    changed('K04 wrong value',['checks',0,'declared_value'],'900.00','VALUE_MISMATCH')
    changed('K06 range escape',['checks',0,'value_range'],{'start':0,'end':36},'REQUEST_INVALID')
    changed('K06 empty',['checks',0,'value_range'],{'start':29,'end':29},'REQUEST_INVALID')
    changed('K07 out of bounds',['checks',0,'quote_range'],{'start':17,'end':40},'RANGE_OUT_OF_BOUNDS')
    changed('K08 source',['source','sha256'],H,'SOURCE_IDENTITY_MISMATCH')
    changed('K09 projection',['expected_page_text_sha256'],H,'PAGE_PROJECTION_MISMATCH')
    changed('K14 declared negative zero',['checks',0,'declared_value'],'-0.00','REQUEST_INVALID')
    changed('K14 scale',['checks',0,'scale'],1,'REQUEST_INVALID')
    for quality,code in [('ocr_required','SELECTED_UNIT_OCR_REQUIRED'),('incomplete','SELECTED_UNIT_INCOMPLETE')]:
        ctx={**context,'quality':quality}
        check('K16 '+quality,lambda ctx=ctx:v.kernel_result(request,ctx)['checks'][0]['reason_code'],code)
    ctx={**context,'page_number':56};req={**request,'page_number':56}
    check('K18 nonexistent',lambda:v.kernel_request(req,ctx),'PAGE_UNAVAILABLE')
    req={**request,'page_number':55};ctx={**context,'page_number':55}
    check('K18 page55',lambda:v.kernel_result(req,ctx)['overall_status'],'pass')
    for raw,scale,out in [('-0.00',2,'0.00'),('1100.00',2,'1100.00'),('1.234',2,'VALUE_CONVERSION_FAILED'),('1e3',0,'VALUE_CONVERSION_FAILED'),('1,000.00',2,'VALUE_CONVERSION_FAILED')]:
        check('decimal '+raw,lambda raw=raw,scale=scale:v.decimal(raw,scale),out)
    # NFC and astral code-point addressing, not UTF-16 indexing.
    req=copy.deepcopy(request);text='e\u0301😀 Amount due: 1100.00\n';n=v.unicodedata.normalize('NFC',text)
    start=n.index('Amount');end=n.index('\n');value_start=n.index('1100')
    req['expected_page_text_sha256']=v.sha(n.encode());req['checks'][0].update(quote='Amount due: 1100.00',quote_range={'start':start,'end':end},value_range={'start':value_start,'end':end})
    ctx={**context,'text':text}
    check('K11 NFC astral',lambda:v.kernel_result(req,ctx)['overall_status'],'pass')
    result=v.kernel_result(request,context)
    semantic_req={k:a for k,a in request.items() if k!='request_id'}
    semantic_req['source']={k:a for k,a in request['source'].items() if k!='document_b64'}
    report={'schema_version':'prodocux_source_binding_report_draft_v1','request_id':request['request_id'],
        'semantic_request_digest':v.digest(semantic_req),'semantic_result':result,'semantic_result_digest':v.digest(result),
        'producer':{'kernel_version':'draft-fixture','parser_backend':'pypdf','parser_backend_version':'fixture'}}
    check('K report valid',lambda:v.kernel_report(report,request,context))
    bad=copy.deepcopy(report);bad['semantic_result']['checks'][0]['evidence']['derived_value']='900.00';bad['semantic_result_digest']=v.digest(bad['semantic_result'])
    check('K report coherently forged digest',lambda:v.kernel_report(bad,request,context),'REQUEST_INVALID')
    bad=copy.deepcopy(report);bad['semantic_result']['coverage']['document_disposition']='complete'
    check('K coverage lie',lambda:v.kernel_report(bad,request,context),'REQUEST_INVALID')



def run():
    kernel_cases()
    return count
