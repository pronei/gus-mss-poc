#!/usr/bin/env python3
# R2/R4: constant-pool scan of every class in a jar (no JDK needed): counts classes carrying
# RuntimeVisibleAnnotations, Signature, MethodParameters, LocalVariableTable, kotlin.Metadata,
# Spring web / Retrofit / Jackson annotation descriptors.  usage: r2_jarscan.py <jar>...
# Constant-pool scan of class files inside a jar: no JDK needed.
import zipfile,struct,sys,collections
def parse_cp(b):
    n=struct.unpack('>H',b[8:10])[0]; i=10; cp=[None]; k=1
    while k<n:
        t=b[i]
        if t==1:
            l=struct.unpack('>H',b[i+1:i+3])[0]; cp.append(b[i+3:i+3+l].decode('utf-8','replace')); i+=3+l
        elif t in (3,4): cp.append(None); i+=5
        elif t in (5,6): cp.append(None); cp.append(None); i+=9; k+=1
        elif t in (7,8,16,19,20): cp.append(None); i+=3
        elif t in (9,10,11,12,17,18): cp.append(None); i+=5
        elif t==15: cp.append(None); i+=4
        else: raise ValueError('cp tag %d'%t)
        k+=1
    return cp
def scan(jar):
    z=zipfile.ZipFile(jar)
    st=collections.Counter(); majors=collections.Counter(); classes=0
    for n in z.namelist():
        if not n.endswith('.class'): continue
        b=z.read(n); classes+=1
        majors[struct.unpack('>H',b[6:8])[0]]+=1
        cp=set(x for x in parse_cp(b) if x)
        for key,pat in [('RuntimeVisibleAnnotations','RuntimeVisibleAnnotations'),('RuntimeVisibleParameterAnnotations','RuntimeVisibleParameterAnnotations'),('Signature','Signature'),('MethodParameters','MethodParameters'),('LocalVariableTable','LocalVariableTable'),('kotlin.Metadata','Lkotlin/Metadata;')]:
            if pat in cp: st[key]+=1
        if any(x.startswith('Lorg/springframework/web/bind/annotation/') for x in cp): st['spring-web-annot']+=1
        if any(x.startswith('Lretrofit') for x in cp): st['retrofit-annot']+=1
        if any(x.startswith('Lcom/fasterxml/jackson/annotation/') for x in cp): st['jackson-annot']+=1
    return classes,majors,st
for jar in sys.argv[1:]:
    c,m,s=scan(jar)
    print(jar.split('/')[-1],'classes',c,'majors',dict(m),dict(s))
