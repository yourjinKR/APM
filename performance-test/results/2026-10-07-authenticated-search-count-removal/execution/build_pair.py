from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone, timedelta

root = Path(__file__).resolve().parent
backend = Path(r'C:\dev\workspace\KnockIn\back\11th-1team-BE')
output = Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-count-removal')
source_files = ['src/main/java/org/example/knockin/board/controller/RoomMateController.java',
                'src/main/java/org/example/knockin/board/repository/RoommateBoardRepositoryCustom.java',
                'src/main/java/org/example/knockin/board/repository/impl/RoommateBoardRepositoryImpl.java',
                'src/main/java/org/example/knockin/board/service/RoommateBoardService.java',
                'src/main/java/org/example/knockin/board/service/impl/RoommateBoardServiceImpl.java']
builds=[]
for variant in ['before-count','after-slice']:
    project = root / variant
    if project.exists():
        raise RuntimeError('Refuse to overwrite an existing isolated build')
    project.mkdir()
    for name in ['src','gradle']:
        shutil.copytree(backend/name,project/name,ignore=shutil.ignore_patterns('firebase*.json'))
    # Copy only the build files; user checkout, compiled IDE classes and Git state stay untouched.
    for name in ['build.gradle','settings.gradle','gradlew','gradlew.bat']:
        shutil.copyfile(backend/name,project/name)
    if variant=='before-count':
        for name in source_files:
            result=subprocess.run(['git','-C',str(backend),'show','HEAD:'+name],capture_output=True,check=True)
            (project/name).write_bytes(result.stdout)
    target=output/'controlled-ab'/variant
    target.mkdir(parents=True)
    print('BUILD '+variant,flush=True)
    with (target/'build.log').open('wb') as log:
        result=subprocess.run(['cmd','/c','gradlew.bat','--offline','--no-daemon','--console=plain','bootJar','-x','test'],
                              cwd=project,stdout=log,stderr=subprocess.STDOUT,timeout=300,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        print((target/'build.log').read_text('utf-8',errors='replace')[-5000:])
        raise RuntimeError('Isolated build failed: '+variant)
    jar=project/'build/libs/KnockIn-0.0.1-SNAPSHOT.jar'
    builds.append({'variant':variant,'jarPath':str(jar),'jarSha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
        'sourceHashes':{name:hashlib.sha256((project/name).read_bytes()).hexdigest() for name in source_files}})
    print('BUILT '+variant,flush=True)
(output/'controlled-ab/builds.json').write_text(json.dumps(builds,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lib=(root/'run_measurement.py').read_text('utf-8').split('if OUTPUT.exists():',1)[0]
(output/'execution/focused_search_lib.py').write_text(lib,encoding='utf-8')
shutil.copyfile(__file__,output/'execution/build_pair.py')
print('Both count-before and Slice-after artifacts ready',flush=True)
