"""Isolated, pinned R-core reader. No apt install, maintainer scripts or shared env changes."""
from intake import *
import subprocess,shutil

VERSION='4.3.3-2build2'
SHA='086f046230727fc896f70cfb459d693023a30a9f6877492554aa7041dac2e576'
URL='https://mirrors.tuna.tsinghua.edu.cn/ubuntu/pool/universe/r/r-base/r-base-core_4.3.3-2build2_amd64.deb'

def main():
    root=ART/'spatial-r-core';root.mkdir(exist_ok=True)
    p=fetch(URL,'r-base-core_4.3.3-2build2_amd64.deb',32*1024**2,metadata=dict(provider='Ubuntu24.04 signed apt metadata',independent_unit='not applicable: software tool',upstream_study_ids=[],release=VERSION,terms_url='https://www.r-project.org/about.html',reuse_basis='R GNU GPL; package extracted into this artifact only, no package scripts or system installation'))
    assert p is not None and hashlib.sha256(p.read_bytes()).hexdigest()==SHA
    assert not (root/'usr/lib/R/bin/exec/R').exists(),'Already extracted; inspect existing reader instead'
    subprocess.run(['dpkg-deb','-x',str(p),str(root)],check=True)
    # Debian's R uses /etc/R symlinks. Replace only links inside our extracted prefix.
    etc=root/'usr/lib/R/etc'
    for q in etc.iterdir():
        if q.is_symlink() and os.readlink(q).startswith('/etc/R/'):
            source=root/'etc/R'/q.name
            if source.exists():q.unlink();shutil.copy2(source,q)
    total=sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())
    assert total<512*1024**2
    missing=subprocess.run(['ldd',str(root/'usr/lib/R/lib/libR.so')],capture_output=True,text=True,check=True).stdout
    atomic(DATA/'spatial_r_tool_lock.json',dict(at=now(),version=VERSION,deb_sha256=SHA,deb_url=URL,installed_bytes=total,prefix=str(root),system_os='Ubuntu24.04',linked_libraries=missing,shared_environment_modified=False,package_install_limit_bytes=512*1024**2))
    print(missing);print('isolated installed bytes',total)

if __name__=='__main__':main()
