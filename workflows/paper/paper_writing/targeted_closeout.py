"""Hash-bound targeted addendum followed by author-side editorial closeout.

Not a replacement full review, score generator, or scientific waiver. The
independent addendum must itself establish scientific readiness. Only remaining
text-only requests can be closed by the separately recorded author-side action.
"""
from pathlib import Path
from paper_writing import minor_closeout as m

FIELD = 'targeted_review_closeout'
SCHEMA = 'openlabs.targeted_review_closeout.v1'


def _complete_snapshot_replay(complete, clean, pdf, expected, names):
    """Replay archived bytes, never overlay a historical document with today’s PDF."""
    m._require(set(complete) == set(names) and 'main.pdf' not in complete,
               'complete snapshot source membership differs')
    m._require(set(clean) <= set(complete)
               and all(complete[n] == value for n, value in clean.items()),
               'clean source archive differs from complete snapshot')
    m._require(m._snapshot(complete, pdf) == expected,
               'complete source/PDF snapshot does not reconstruct')
    return complete


def _pdf_text(value):
    """Independently extract actual PDF bytes, rather than trust a receipt boolean."""
    import subprocess
    m._require(value.startswith(b'%PDF-') and len(value) <= 16 * 1024 * 1024,
               'invalid or oversized derived PDF')
    result = subprocess.run(['pdftotext', '-layout', '-', '-'], input=value,
                            capture_output=True, timeout=30, check=True)
    m._require(len(result.stdout) <= 8 * 1024 * 1024, 'oversized derived PDF text')
    return result.stdout.decode('utf-8')


def _clean_build_inputs(sources):
    from paper_writing.handoff import CLEAN_SOURCE_SUFFIXES
    return {n: v for n, v in sources.items()
            if Path(n).suffix in CLEAN_SOURCE_SUFFIXES and Path(n).suffix != '.bbl'
            and not (Path(n).parent == Path('.') and Path(n).suffix == '.pdf')}


def _recorded_document_inputs(recorder, inputs, source):
    """Read the actual TeX recorder; changed figures or included TeX stay forbidden."""
    from pathlib import PurePosixPath
    lines = recorder.decode('utf-8').splitlines()
    roots = [line[4:] for line in lines if line.startswith('PWD ')]
    m._require(len(roots) == 1 and PurePosixPath(roots[0]).is_absolute(),
               'missing or ambiguous clean-build recorder directory')
    root = PurePosixPath(roots[0])
    system = ('/etc/texmf', '/usr/share/texmf', '/usr/share/texlive',
              '/var/lib/texmf', '/usr/share/fonts')
    generated = {str(Path(source).with_suffix(s)) for s in ('.aux', '.out', '.toc', '.bbl')}
    used = set()
    for line in lines:
        if not line.startswith('INPUT '):
            continue
        path = PurePosixPath(line[6:])
        m._require('..' not in path.parts and '\\' not in str(path),
                   'unsafe clean-build recorder input')
        if path.is_absolute():
            if path.is_relative_to(root):
                path = path.relative_to(root)
            else:
                m._require(any(path.is_relative_to(p) for p in system),
                           'unbound external clean-build input')
                continue
        name = str(path)
        m._require('..' not in path.parts and '\\' not in name
                   and (name in inputs or name in generated),
                   'unbound local clean-build input: ' + name)
        if name in inputs:
            used.add(name)
    m._require(source in used and str(Path(source).with_suffix('.bbl')) in
               {str(PurePosixPath(line[6:])).removeprefix(str(root) + '/')
                for line in lines if line.startswith('INPUT ')},
               'recorder omitted the document or generated bibliography')
    return str(root), used


def _derived_document_delta(before, after, authorization, assessment, packet):
    """One explicitly reviewed bibliography-date rebuild; never a PDF allowlist.

    This applies only before the independent addendum. The final editorial delta
    still uses minor_closeout._deltas, so every ancillary PDF then stays frozen.
    """
    import hashlib
    import re
    packet = Path(packet)
    updates = authorization.get('derived_document_updates', [])
    m._require(isinstance(updates, list) and len(updates) == 1,
               'exactly one authorized derived document update required')
    update = updates[0]
    m._keys(update, {'path', 'source', 'before_sha256', 'after_sha256', 'source_sha256',
                     'input_changes', 'date_correction', 'evidence_sha256'}, 'derived document update')
    name = update['path'].removeprefix('manuscript/')
    source = update['source'].removeprefix('manuscript/')
    m._require(update['path'] == 'manuscript/' + name and Path(name).name == name
               and name != 'main.pdf' and Path(name).suffix == '.pdf'
               and update['source'] == 'manuscript/' + source
               and source == str(Path(name).with_suffix('.tex'))
               and name in before and name in after and source in before and source in after,
               'derived update must name an existing root PDF and matching TeX')
    sha = lambda value: hashlib.sha256(value).hexdigest()
    row = {'path': update['path'], 'before_sha256': sha(before[name]), 'after_sha256': sha(after[name])}
    m._require(all(update[k] == v for k, v in row.items()) and before[name] != after[name]
               and before[source] == after[source] and sha(before[source]) == update['source_sha256'],
               'derived PDF or unchanged TeX binding differs')
    correction = update['date_correction']
    m._keys(correction, {'before', 'after'}, 'bibliography date correction')
    # This compatibility repair has one concrete documentary purpose. A new
    # correction needs its own reviewed implementation, not an arbitrary string.
    m._require(correction == {'before': 'October 2022', 'after': '29 September 2022'},
               'unsupported bibliography date correction')
    changed = update['input_changes']
    bbl = str(Path(source).with_suffix('.bbl'))
    m._require(isinstance(changed, list) and len(changed) == 2
               and [r['path'] for r in changed] == sorted(r['path'] for r in changed)
               and len({r['path'] for r in changed}) == 2,
               'derived input change inventory is not exact')
    changed_names = {r['path'].removeprefix('manuscript/') for r in changed}
    bibs = [n for n in changed_names if Path(n).suffix == '.bib' and Path(n).name == n]
    m._require(len(bibs) == 1 and changed_names == {bibs[0], bbl},
               'derived inputs must be one shared bibliography and its generated bbl')
    for change in changed:
        m._keys(change, {'path', 'before_sha256', 'after_sha256'}, 'derived input change')
        n = change['path'].removeprefix('manuscript/')
        m._require(change['path'] == 'manuscript/' + n and n in before and n in after
                   and sha(before[n]) == change['before_sha256'] and sha(after[n]) == change['after_sha256'],
                   'derived input hash differs')
        # BibTeX wraps the longer date across a line; its exact generated bytes
        # are also checked against all three actual builds below.
        normalize = (lambda v: re.sub(rb'\s+', b'', v)) if n == bbl else (lambda v: v)
        old, new = normalize(before[n]), normalize(after[n])
        old_date, new_date = (normalize(correction[k].encode()) for k in ('before', 'after'))
        m._require(old.count(old_date) == 1 and old.replace(old_date, new_date) == new,
                   'derived input contains more than the exact bibliography date correction')
    proof_path = m._bound({'path': 'derived-document-proof.json',
                           'sha256': update['evidence_sha256']}, packet)
    proof = m._json(proof_path)
    m._keys(proof, {'schema_version', 'complete_snapshots', 'builds'}, 'derived build proof')
    m._require(proof['schema_version'] == 'openlabs.derived_document_date_build.v1',
               'unsupported derived build proof schema')
    complete = proof['complete_snapshots']
    m._keys(complete, {'baseline', 'reviewed'}, 'reviewed complete snapshots')
    for stage, sources in [('baseline', before), ('reviewed', after)]:
        m._require(m._archive(m._bound(complete[stage], packet)) == sources,
                   'referee did not receive the complete ' + stage + ' sources')
    builds = proof['builds']
    m._require(isinstance(builds, list) and [b.get('stage') for b in builds] ==
               ['baseline', 'reviewed', 'standalone'], 'missing or duplicate clean builds')
    texts, directories, dependencies = [], [], []
    for build in builds:
        m._keys(build, {'stage', 'input_archive', 'pdf', 'text', 'recorder', 'log',
                        'bibliography_log', 'bbl'}, 'derived clean build')
        files = {key: m._bound(value, packet) for key, value in build.items() if key != 'stage'}
        sources = before if build['stage'] == 'baseline' else after
        inputs = m._archive(files['input_archive'])
        m._require(inputs == _clean_build_inputs(sources), 'clean build input archive differs')
        m._require(files['bbl'].read_bytes() == sources[bbl], 'clean build bibliography differs')
        directory, used = _recorded_document_inputs(files['recorder'].read_bytes(), inputs, source)
        directories.append(directory)
        dependencies.append(used | {bibs[0]})
        biblog = files['bibliography_log'].read_text()
        m._require(re.findall(r'^Database file #\d+: (.+)$', biblog, re.MULTILINE) == bibs,
                   'clean build did not use the bound shared bibliography')
        log = files['log'].read_text()
        m._require('Output written on ' + name + ' (' in log and not re.search(r'^!', log, re.MULTILINE)
                   and 'undefined' not in log.lower(), 'derived clean build failed or has unresolved references')
        actual = _pdf_text(files['pdf'].read_bytes())
        m._require(actual == files['text'].read_text(), 'clean-build PDF text evidence differs')
        m._require(actual == _pdf_text(sources[name]), 'clean-build PDF differs from its canonical document')
        texts.append(actual)
    m._require(len(set(directories)) == 3 and dependencies[0] == dependencies[1] == dependencies[2],
               'clean builds are not distinct or document dependencies differ')
    m._require(all(before[n] == after[n] for n in dependencies[0] - changed_names),
               'derived document scientific source or figure changed')
    compact = lambda value: re.sub(r'\s+', '', value)
    old_date, new_date = map(compact, (correction['before'], correction['after']))
    m._require(compact(texts[0]).count(old_date) == 1
               and compact(texts[0]).replace(old_date, new_date) == compact(texts[1])
               and texts[1] == texts[2], 'derived PDF contains more than the exact date correction')
    # Machine evidence can be preflighted with an empty assessment. It must
    # still stop here: no author-generated readiness judgment is substituted.
    inspected = assessment.get('derived_document_updates_reviewed', [])
    m._require(len(inspected) == 1 and inspected[0].get('update') == update
               and inspected[0].get('evidence_sha256') == m._sha(proof_path)
               and inspected[0].get('ready') is True and m._text(inspected[0].get('reason')),
               'independent derived-document assessment missing or blocking')
    return row


def _support_digests(path, version):
    """Bounded-memory comparison of complete payloads, including large archives.

    This never treats archive CRCs or a manifest as proof of member equality.
    Every uncompressed member is streamed through SHA-256; path checks remain
    identical to the small-archive reader. No payload is dropped or truncated.
    """
    import hashlib
    import zipfile
    from pathlib import PurePosixPath
    result = {}
    with zipfile.ZipFile(path) as archive:
        m._require(len(archive.infolist()) <= 10000, 'too many support members')
        for item in archive.infolist():
            name = item.filename
            p = PurePosixPath(name)
            m._require(not p.is_absolute() and '..' not in p.parts and '\\' not in name
                       and (item.external_attr >> 16) & 0o170000 != 0o120000,
                       'unsafe archive member')
            if item.is_dir():
                continue
            key = next(iter(m._support_members({name: b''}, version)))
            m._require(key not in result, 'duplicate normalized support member')
            digest = hashlib.sha256()
            size = 0
            with archive.open(item) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            m._require(size == item.file_size, 'support member size mismatch')
            result[key] = digest.hexdigest()
    return result


def _documentary_support_path(name):
    # CLAIMS.yaml is declarative claim-to-evidence mapping, not executable code.
    # It is accepted only through the exact independently reviewed delta below.
    return Path(name).suffix in {'.md', '.svg'} or Path(name).name == 'CLAIMS.yaml'


def _tex_document_body(prefix):
    """Conservative lexical tripwire, not a TeX interpreter or semantic proof."""
    import re
    if '^^' in prefix or any(ord(char) < 32 and char not in '\n\t' for char in prefix):
        return False
    forbidden = {'catcode', 'csname', 'endcsname', 'scantokens', 'detokenize',
                 'verb', 'Verb', 'lstinline', 'inputminted', 'lstinputlisting',
                 'begingroup', 'endgroup', 'bgroup', 'egroup', 'everypar',
                 'everymath', 'everydisplay', 'obeylines', 'obeyspaces',
                 'expandafter', 'noexpand', 'futurelet', 'if', 'ifx', 'ifnum',
                 'ifdim', 'ifcat', 'ifcase', 'ifdefined', 'ifcsname', 'ifodd',
                 'iftrue', 'iffalse', 'else', 'fi', 'endinput', 'stop', 'enddocument'}
    definitions = {'def', 'gdef', 'edef', 'xdef', 'let', 'newcommand', 'renewcommand',
                   'providecommand', 'newenvironment', 'renewenvironment', 'global',
                   'long', 'outer', 'makeatletter', 'makeatother'}
    body_commands = {'begin', 'end', 'section', 'subsection', 'subsubsection', 'label',
                     'Cref', 'cref', 'ref', 'eqref', 'cite', 'citep', 'citet', 'emph',
                     'textbf', 'textit', 'texttt', 'footnote', 'url', 'href', 'maketitle',
                     'par', 'noindent', 'smallskip', 'medskip', 'bigskip',
                     '\\', '~', "'", '"', '^', '`', '=', '.', '%', '#', '&', '_', '{', '}', '$', '[', '('}
    opaque_environments = {'verbatim', 'Verbatim', 'lstlisting', 'minted', 'comment',
                           'filecontents', 'filecontents*', 'luacode', 'luacode*'}
    preamble_commands = {'documentclass', 'usepackage', 'hypersetup', 'makeatletter',
                         'makeatother', 'let', 'newtheorem', 'setlength', 'newcommand',
                         'journal', 'theoremstyle', 'title', 'author', 'date', 'begin'}
    environments, math = [], []
    document_seen = False
    depth = 0
    index = 0
    while index < len(prefix):
        char = prefix[index]
        if char == '%':
            end = prefix.find('\n', index)
            index = len(prefix) if end < 0 else end + 1
            continue
        if char == '\\':
            command = re.match(r'\\([A-Za-z@]+|[^\n])', prefix[index:])
            if command is None:
                return False
            name = command[1]
            index += len(command[0])
            if name in forbidden:
                return False
            if not document_seen:
                if not depth and not math and name not in preamble_commands:
                    return False
                if name == 'let':
                    # Existing elsarticle title-style alias; no structural aliasing.
                    alias = re.match(r'\s*\\ps@pprintTitle\s*\\ps@plain\b', prefix[index:])
                    if alias is None:
                        return False
                    index += len(alias[0])
                elif name == 'newcommand':
                    target = re.match(r'\s*\{\\([A-Za-z@]+)\}', prefix[index:])
                    if target is None or target[1] in body_commands | forbidden | definitions:
                        return False
            if document_seen and (name in definitions or (environments == ['document']
                    and not depth and not math and name not in body_commands)):
                return False
            if name in {'begin', 'end'}:
                # TeX permits comments and whitespace between the command and argument.
                while index < len(prefix) and (prefix[index].isspace() or prefix[index] == '%'):
                    if prefix[index] == '%':
                        end = prefix.find('\n', index)
                        index = len(prefix) if end < 0 else end + 1
                    else:
                        index += 1
                argument = re.match(r'\{([A-Za-z][A-Za-z0-9*:_-]*)\}', prefix[index:])
                if argument is None or depth:
                    return False
                environment = argument[1]
                index += len(argument[0])
                if environment in opaque_environments:
                    return False
                if environment == 'document':
                    if name != 'begin' or document_seen:
                        return False
                    document_seen = True
                if name == 'begin':
                    environments.append(environment)
                elif not environments or environments.pop() != environment:
                    return False
            elif name in {'(', '['}:
                if math:
                    return False
                math.append(name)
            elif name in {')', ']'}:
                if not math or math.pop() != {')': '(', ']': '['}[name]:
                    return False
            continue
        if char in '{}':
            depth += 1 if char == '{' else -1
            if depth < 0:
                return False
        elif char == '$':
            delimiter = '$$' if prefix.startswith('$$', index) else '$'
            index += len(delimiter) - 1
            if math:
                if math.pop() != delimiter:
                    return False
            else:
                math.append(delimiter)
        index += 1
    return environments == ['document'] and depth == 0 and not math


def _plain_tex_paragraph(source, paragraph):
    """One complete plain paragraph immediately after a simple section heading.

    Restricting this opt-in avoids treating an arbitrary TeX hunk as prose. All
    other source bytes must separately remain identical; the independent
    addendum still judges whether the correction preserves scientific meaning.
    """
    import re
    m._require(isinstance(paragraph, str) and 0 < len(paragraph) <= 4096
               and paragraph.strip() == paragraph
               and all(char == '\n' or 32 <= ord(char) <= 126 for char in paragraph)
               and not any(char in paragraph for char in '\\{}$&#_^%~')
               and not re.search(r'\n[ \t]*\n', paragraph), 'not a plain TeX prose paragraph')
    text = source.decode('utf-8')
    m._require(text.count(paragraph) == 1, 'TeX prose paragraph is missing or ambiguous')
    start = text.index(paragraph)
    end = start + len(paragraph)
    m._require(start > 0 and text[start - 1] == '\n' and text[end:end + 2] == '\n\n',
               'TeX prose edit is not a complete paragraph')
    heading = text[:start - 1].rsplit('\n', 1)[-1]
    m._require(re.fullmatch(r'\\(?:section|subsection|subsubsection)\{[^{}\\\n]+\}'
                           r'(?:\\label\{[A-Za-z0-9:._-]+\})?', heading) is not None,
               'TeX prose paragraph must directly follow a simple section heading')
    m._require(_tex_document_body(text[:start]), 'TeX prose paragraph has unsupported context')
    return heading


def _support_tex_member(path, version, normalized_name):
    """Read the one exact normalized member, never a suffix-matching packet copy."""
    import zipfile
    from pathlib import PurePosixPath
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        m._require(len(members) <= 10000, 'too many support members')
        selected = []
        for item in members:
            name = PurePosixPath(item.filename)
            m._require(not name.is_absolute() and '..' not in name.parts
                       and '\\' not in item.filename
                       and (item.external_attr >> 16) & 0o170000 != 0o120000,
                       'unsafe support TeX archive member')
            if not item.is_dir() and next(iter(m._support_members({item.filename: b''}, version))) == normalized_name:
                selected.append(item)
        m._require(len(selected) == 1 and selected[0].file_size <= 2 * 1024 * 1024,
                   'missing, ambiguous or oversized support TeX member')
        return archive.read(selected[0])


def _validated_support_tex_prose_changes(authorization, assessment, packet, before, reviewed,
                                         final, delta, old_archive, new_archive,
                                         old_version, new_version, old_inventory, new_inventory):
    """Exact mirrored prose opt-in, within the outer paper/version-bound addendum.

    Packet contract: complete before/<path> and <path> files for both sources;
    manuscript-tex-prose.diff and support-tex-prose.diff are UTF-8 unified diffs
    with 12 context lines, fromfile='before/'+path, tofile=path. The independent
    assessment binds their hashes and explains why both diffs preserve science.
    """
    import difflib
    import hashlib
    from pathlib import PurePosixPath
    from paper_writing.review_delta import scope_reasons
    changes = authorization.get('support_tex_prose_only_changes', [])
    inspected = assessment.get('support_tex_prose_only_reviewed', [])
    if not changes and not inspected:
        return {}
    m._require(isinstance(changes, list) and len(changes) == 1
               and isinstance(inspected, list) and len(inspected) == 1,
               'one authorized and independently inspected TeX prose change required')
    entry, judgment = changes[0], inspected[0]
    identities = {'path', 'before_sha256', 'after_sha256', 'manuscript_path',
                  'manuscript_before_sha256', 'manuscript_after_sha256'}
    m._keys(entry, identities | {'before_paragraph', 'after_paragraph'}, 'TeX prose authorization')
    m._keys(judgment, identities | {'manuscript_diff_sha256', 'support_diff_sha256',
                                  'both_diffs_reviewed', 'scientific_content_unchanged', 'reason'},
            'independent TeX prose assessment')
    m._require(all(judgment[key] == entry[key] for key in identities)
               and judgment['both_diffs_reviewed'] is True
               and judgment['scientific_content_unchanged'] is True and m._text(judgment['reason']),
               'independent TeX prose assessment missing or blocking')
    support_name = entry['path']
    manuscript_name = entry['manuscript_path']
    m._require(isinstance(support_name, str) and support_name.startswith('support/')
               and PurePosixPath(support_name).name == 'proofs.tex' and '\\' not in support_name
               and '..' not in PurePosixPath(support_name).parts
               and PurePosixPath(support_name).as_posix() == support_name
               and manuscript_name == 'manuscript/main.tex', 'invalid mirrored TeX prose paths')
    normalized = next(iter(m._support_members(
        {f'archive-support-v{new_version}/' + support_name[8:]: b''}, new_version)))
    controls = {'ZENODO_MANIFEST.json', 'SHA256SUMS', 'ARA_SUPPORT_README.md'}
    m._require(set(old_inventory) == set(new_inventory)
               and all(old_inventory[name] == new_inventory[name]
                       for name in old_inventory if name != normalized and name not in controls),
               'TeX prose route cannot change other supporting inputs')
    support = (_support_tex_member(old_archive, old_version, normalized),
               _support_tex_member(new_archive, new_version, normalized))
    m._require(set(before) == set(reviewed) and reviewed == final and 'main.tex' in before
               and all(before[name] == reviewed[name] for name in before if name != 'main.tex'),
               'TeX prose route cannot mix other manuscript or postreview changes')
    manuscript = (before['main.tex'], reviewed['main.tex'])
    digest = lambda value: hashlib.sha256(value).hexdigest()
    expected_delta = [
        {'path': manuscript_name, 'before_sha256': digest(manuscript[0]), 'after_sha256': digest(manuscript[1])},
        {'path': support_name, 'before_sha256': digest(support[0]), 'after_sha256': digest(support[1])},
    ]
    m._require(delta == expected_delta, 'TeX prose route requires exactly the two actual source deltas')
    headings = []
    for area, name, values, prefix in (('manuscript', manuscript_name, manuscript, 'manuscript_'),
                                      ('support', support_name, support, '')):
        m._require([digest(value) for value in values] ==
                   [entry[prefix + 'before_sha256'], entry[prefix + 'after_sha256']],
                   'full TeX source hashes differ')
        for side, value, paragraph in zip(('before/', ''), values,
                                          (entry['before_paragraph'], entry['after_paragraph'])):
            headings.append(_plain_tex_paragraph(value, paragraph))
            path = Path(packet) / (side + name)
            m._require(path.is_file() and not any(p.is_symlink() for p in [path, *path.parents])
                       and path.read_bytes() == value, 'reviewer did not receive complete actual TeX sources')
        old_text, new_text = entry['before_paragraph'].encode(), entry['after_paragraph'].encode()
        m._require(old_text != new_text and values[0].replace(old_text, new_text, 1) == values[1]
                   and not scope_reasons({'main.tex': values[0]}, {'main.tex': values[1]}),
                   'TeX prose delta changes bytes outside the authorized paragraph or native scope')
        actual_diff = ''.join(difflib.unified_diff(values[0].decode().splitlines(True),
            values[1].decode().splitlines(True), fromfile='before/' + name, tofile=name, n=12)).encode()
        path = Path(packet) / (area + '-tex-prose.diff')
        m._require(path.is_file() and not path.is_symlink() and path.read_bytes() == actual_diff
                   and judgment[area + '_diff_sha256'] == digest(actual_diff),
                   'independent reviewer did not inspect the actual TeX diff')
    m._require(len(set(headings)) == 1, 'manuscript and support prose section contexts differ')
    return {normalized: expected_delta[1]}


def _authorized_module_docstring_delta(row, authorization, assessment, packet):
    """Exact opt-in documentation edit, not permission to change executable AST.

    The isolated referee must also assess docstring use at runtime. Byte equality
    outside the leading string prevents an AST-equivalent code rewrite slipping
    through. Authorization is already paper/version bound by validate().
    """
    import ast
    import hashlib
    if (row not in authorization.get('support_docstring_only_changes', [])
            or row['path'] not in assessment.get('support_docstring_only_reviewed', [])
            or not row['path'].startswith('support/') or not row['path'].endswith('.py')):
        return False
    relative = Path(row['path'])
    if '..' in relative.parts or relative.is_absolute():return False
    values = [(Path(packet)/'before'/relative).read_bytes(), (Path(packet)/relative).read_bytes()]
    if [hashlib.sha256(v).hexdigest() for v in values] != [row['before_sha256'], row['after_sha256']]:return False
    stripped=[]
    for value in values:
        try:
            tree=ast.parse(value)
            node=tree.body[0]
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):return False
            lines=value.splitlines(keepends=True)
            start=sum(map(len,lines[:node.lineno-1]))+node.col_offset
            end=sum(map(len,lines[:node.end_lineno-1]))+node.end_col_offset
            stripped.append(value[:start]+b'"""DOCSTRING"""'+value[end:])
            # Only the conventional argparse help description may consume it.
            # The independently supplied assessment still decides semantic scope.
            parents={child:parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for n in ast.walk(tree):
                if isinstance(n,ast.Attribute) and n.attr=='__doc__':return False
                if not (isinstance(n,ast.Name) and n.id=='__doc__'):continue
                kw=parents.get(n);call=parents.get(kw)
                if not (isinstance(kw,ast.keyword) and kw.arg=='description'
                        and isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                        and isinstance(call.func.value,ast.Name) and call.func.value.id=='argparse'
                        and call.func.attr=='ArgumentParser'):return False
        except (SyntaxError,IndexError,UnicodeError):return False
    return stripped[0]==stripped[1]


def _cumulative_manuscript_delta(before, after, authorization, provenance, assessment):
    """Permit new publisher template assets only when byte-bound and reviewed.

    This is exclusive to an explicitly authorized targeted addendum. It does not
    make a global-template change eligible for ordinary automatic delta reuse.
    Removed files and new scientific sources remain forbidden.
    """
    from urllib.parse import urlparse
    additions = sorted(set(after) - set(before))
    m._require(not (set(before) - set(after)), 'removed manuscript input')
    if not additions:
        return m._deltas(before, after, 'manuscript')
    assets = authorization.get('template_asset_sha256', {})
    m._require(set(assets) == set(additions)
               and provenance.get('files') == assets
               and sorted(assessment.get('template_assets_reviewed', [])) == additions,
               'new template files lack exact authorization/provenance/review')
    url = urlparse(provenance.get('url', ''))
    m._require(url.scheme == 'https' and url.hostname is not None
               and (url.hostname == 'springernature.com'
                    or url.hostname.endswith('.springernature.com')
                    or url.hostname.endswith('.springernature.io')),
               'unverified publisher template provenance')
    import hashlib
    for name in additions:
        m._require(Path(name).name == name and Path(name).suffix in {'.cls', '.bst', '.sty'}
                   and hashlib.sha256(after[name]).hexdigest() == assets[name],
                   'new manuscript file exceeds publisher template boundary')
    result = m._deltas(before, {n: after[n] for n in before}, 'manuscript')
    result += [{'path': 'manuscript/' + n, 'before_sha256': None,
                'after_sha256': assets[n]} for n in additions]
    return sorted(result, key=lambda row: row['path'])


def _integrity_rebinding_from_archives(name, old_path, new_path, old_version, new_version):
    """Read only the verifier and sibling manifest, then use the strict checker."""
    import zipfile
    if Path(name).name != 'verify_support_bundle.py':
        return False
    needed = {name, str(Path(name).parent / 'evidence_bundle_manifest.json')}
    def selected(path, version):
        found = {}
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                key = next(iter(m._support_members({item.filename: b''}, version)))
                if key not in needed:
                    continue
                m._require(key not in found and item.file_size <= 2 * 1024 * 1024,
                           'oversized or duplicate integrity metadata')
                found[key] = archive.read(item)
        return found
    before, after = selected(old_path, old_version), selected(new_path, new_version)
    return name in before and name in after and m._integrity_verifier_rebinding(
        name, before[name], after[name], before, after, old_version, new_version)


def _validate_code_first_repackaging(old, new, packet, authorization, assessment,
                                    old_archive_sha256, new_archive_sha256):
    """Explicitly authorized inventory revision, independently assessed, not reuse.

    Keep the full old evidence hash-bound. Scientific construction modules and
    retained entry points cannot change. Only a new orchestration entry point and
    compact summary may be added. Missing-input judgments belong to the isolated
    reviewer, not to filename heuristics or the author-side closeout.
    """
    import hashlib
    packet = Path(packet)
    inventory_path = packet / 'support-repackaging.json'
    inventory = m._json(inventory_path)
    sha = m._sha(inventory_path)
    changes = [{'path': n, 'before_sha256': old.get(n), 'after_sha256': new.get(n)}
               for n in sorted(set(old) | set(new)) if old.get(n) != new.get(n)]
    m._require(authorization.get('actor') == 'user' and authorization.get('confirmed') is True
               and m._text(authorization.get('quote'))
               and authorization.get('scope') == 'code_first_repackaging_targeted_review'
               and authorization.get('inventory_sha256') == sha,
               'explicit exact-inventory repackaging authorization required')
    m._require(inventory == {'before': old, 'after': new, 'changes': changes,
                'baseline_archive_sha256': old_archive_sha256,
                'current_archive_sha256': new_archive_sha256},
               'support repackaging inventory differs from complete archives')
    m._require(assessment.get('inventory_sha256') == sha
               and all(assessment.get(k) is True for k in
                       ('ready', 'unchanged_scientific_code', 'no_required_input_lost',
                        'documentation_matches_manuscript'))
               and sorted(assessment.get('changed_paths_reviewed', [])) == [r['path'] for r in changes]
               and m._text(assessment.get('reason')),
               'independent support repackaging assessment incomplete or blocking')
    for name, digest in old.items():
        path = Path(name)
        if path.parent.name == 'src' or path.name in {'requirements.txt', 'LICENSE', 'LICENSE.txt'}:
            m._require(new.get(name) == digest, 'scientific source/dependency/license lost or changed: ' + name)
        if name in new and path.suffix == '.py':
            m._require(new[name] == digest, 'retained scientific entry point changed: ' + name)
    for name in set(new) - set(old):
        m._require(name in {'support-materials/public-support-v{version}/reproduce.py',
                           'support-materials/public-support-v{version}/reference-summary.json'},
                   'new support input exceeds code-first orchestration scope: ' + name)
    # The referee must receive the exact complete CURRENT public file set, not
    # just a coordinator-generated list or a prose claim that code was retained.
    actual = {str(p.relative_to(packet/'current-support')): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (packet/'current-support').rglob('*') if p.is_file()}
    m._require(actual == new, 'reviewer did not receive the exact complete current public package')


def validate(paper_id, certificate, metadata, root):
    from paper_writing.handoff import _source_files, _verified_journal_source_archive
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.registry import load_registry_settings
    from paper_writing.review import validate_review_panel_files, reviewer_role_for_domain
    from paper_writing.revision_policy import revision_round_policy
    from paper_writing.support import verify_support_archive, resolve_support_sources, _record_version
    from paper_writing.zenodo import _verify_archive_sources
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_blockers
    from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers

    root = Path(root).resolve()
    path = m._path(certificate, root)
    cert = m._json(path)
    m._require(cert['schema_version'] == SCHEMA and cert['paper_id'] == paper_id,
               'invalid targeted closeout identity')
    evidence = [path]
    def bound(row, artifact=False):
        p = m._bound(row, root, artifact=artifact)
        if not artifact:
            evidence.append(p)
        return p
    bindings = cert['bindings']
    for row in bindings.values():
        bound(row)
    for row in cert['artifact_bindings'].values():
        bound(row, True)
    auth = m._json(bound(bindings['authorization']))
    m._require(auth['actor'] == 'user' and auth['confirmed'] is True
               and auth['paper_id'] == paper_id and m._text(auth['quote'])
               and auth['scope'] == 'targeted_addendum_then_text_only_closeout'
               and auth['target_version'] == metadata['version'] == cert['target']['version'],
               'explicit version-scoped targeted closeout authorization required')
    m._timestamp(auth['recorded_at'])
    baseline = m._json(bound(bindings['baseline_review']))
    panel_path = bound(bindings['baseline_panel'])
    panel = m._json(panel_path)
    errors = validate_review_panel_files(panel, review_path=panel_path, repo_root=root,
        expected_role=reviewer_role_for_domain(metadata['domain']), expected_paper_id=paper_id)
    m._require(not errors, 'invalid original review: ' + '; '.join(errors))
    records = panel['review_metadata']['review_panel']['reviewer_records']
    m._require(len(records) == 1 and records[0]['sha256'] == bindings['baseline_review']['sha256']
               == auth['source_review_sha256'], 'baseline review mismatch')
    applied_record = m._json(bound(bindings['baseline_apply']))
    # Historical final-gate.json records store the same gate at the root.
    # Bind the original record, never manufacture a replacement application.
    applied = applied_record.get('quality_gate', applied_record)
    m._require(applied['score'] == baseline['scores']['overall'] >= 5
               and applied['decision'] == baseline['recommendations']['cas_zone_1_journal']['decision']
               and applied['manuscript_snapshot_sha256'] == baseline['review_metadata']['manuscript_snapshot_sha256_before'],
               'original applied judgment mismatch')
    addendum = m._json(bound(bindings['addendum']))
    execution = m._json(bound(cert['artifact_bindings']['execution'], True))
    snapshot = m._json(bound(cert['artifact_bindings']['snapshot'], True))
    m._require(execution['paper_id'] == snapshot['paper_id'] == paper_id
               and execution['return_code'] == 0 and execution['fresh_ephemeral_process'] is True
               and execution['author_conversation_supplied'] is False
               and execution['prior_review_intentionally_included'] is True
               and execution['new_full_review'] is False
               and execution['isolation'] == 'ephemeral_read_only_mount_isolation'
               and execution['output_sha256'] == bindings['addendum']['sha256']
               and execution['input_hashes'] == snapshot['input_hashes']
               and execution['canonical_snapshot'] == snapshot['canonical_snapshot'],
               'targeted reviewer execution is not bound to its inputs/output')
    packet = bound(cert['artifact_bindings']['snapshot'], True).parent / 'packet'
    actual_inputs = {str(p.relative_to(packet)): m._sha(p) for p in packet.rglob('*') if p.is_file()}
    m._require(actual_inputs == snapshot['input_hashes'], 'targeted packet changed')
    m._require(m._sha(packet / 'baseline-review.json') == bindings['baseline_review']['sha256'],
               'targeted reviewer saw a different baseline')
    m._require(addendum['scope'] == 'targeted_addendum_not_full_review'
               and addendum['original_scores_unchanged'] is True
               and addendum['scientific_ready'] is True
               and addendum['cas_zone_1_decision'] in {'minor_revision', 'accept'},
               'independent scientific readiness/CAS threshold not met')
    dispositions = addendum['request_dispositions']
    # Some isolated reviewers label the complete original list 1..N. Retain
    # their raw judgment unchanged and bind the explicit indexing convention.
    index_base = cert.get('request_index_base', 0)
    m._require(type(index_base) is int and index_base in {0, 1}, 'invalid request index base')
    m._require(sorted(r['index'] - index_base for r in dispositions) == list(range(len(baseline['change_requests'])))
               and all(r['status'] in {'open', 'closed'} and m._text(r['reason']) for r in dispositions),
               'missing or duplicate original request dispositions')
    open_requests = [r['index'] - index_base for r in dispositions if r['status'] == 'open']
    m._require(all(baseline['change_requests'][i].get('text_only') is True for i in open_requests),
               'author-side closeout cannot resolve scientific requests')
    m._require(cert['closed_text_request_indices'] == open_requests,
               'final closeout must cover exactly the open text requests')
    rows = cert['remaining_blocker_resolutions']
    m._require([r['blocker'] for r in rows] == addendum['remaining_blockers']
               and all(r['classification'] in {'text_only_closed', 'nonblocking_venue_only'}
                       and m._text(r['reason']) for r in rows), 'unclassified addendum blocker')
    for row in rows:
        if row['classification'] == 'nonblocking_venue_only':
            m._require('four-leading-journal' in row['blocker'] and 'not a proof defect' in row['blocker']
                       and 'not' in row['blocker'] and 'blocker' in row['blocker'],
                       'venue limitation must be explicitly self-qualified by reviewer')
        else:
            m._require(any(word in row['blocker'].lower() for word in ('whitespace', 'wrapping', 'bibliography')),
                       'not an editorial blocker')
    # Reconstruct the exact reviewed intermediate snapshot, then allow only the
    # explicitly hash-bound final editorial delta. No hidden source change fits.
    manuscript = root / metadata['manuscript_dir']
    pdf = root / metadata['latest_pdf']
    sources = {str(p.relative_to(manuscript)): p.read_bytes() for p in _source_files(manuscript, pdf)}
    verified_zip = _verified_journal_source_archive(metadata, root, manuscript,
        list(_source_files(manuscript, pdf)), None)
    m._require(verified_zip is not None, 'missing verified clean source archive')
    intermediate = m._archive(bound(bindings['reviewed_source_archive']))
    final_zip = m._archive(verified_zip[0])
    m._require(set(intermediate) == set(final_zip)
               and all(sources.get(n) == v for n, v in final_zip.items()),
               'journal source archive membership or bytes differ')
    derived = bool(auth.get('derived_document_updates'))
    full_keys = {'baseline_snapshot_sources', 'reviewed_snapshot_sources'}
    m._require(derived == bool(full_keys & set(cert['artifact_bindings']))
               and (not derived or full_keys <= set(cert['artifact_bindings'])),
               'complete snapshot archives require exact derived-document opt-in')
    extras = [{'path': n, 'sha256': m._members({n: v})[n], 'in_review_packet': False}
              for n, v in sources.items() if n not in final_zip]
    if derived:
        reviewed = _complete_snapshot_replay(
            m._archive(bound(cert['artifact_bindings']['reviewed_snapshot_sources'], True)),
            intermediate, bound(bindings['reviewed_pdf']).read_bytes(),
            snapshot['canonical_snapshot'], sources)
    else:
        reviewed = {**intermediate, **{r['path']: sources[r['path']] for r in extras}}
        m._require(m._snapshot(reviewed, bound(bindings['reviewed_pdf']).read_bytes())
                   == snapshot['canonical_snapshot'], 'reviewed full snapshot does not reconstruct')
    final_delta = m._deltas(reviewed, sources, 'manuscript')
    m._require(final_delta == cert['final_editorial_delta'], 'unreviewed final delta')
    m._require(all(row['path'] in auth['final_editorial_files'] for row in final_delta)
               and auth['final_editorial_files'] == cert['final_editorial_files'],
               'final delta exceeds authorized editorial files')
    # The preceding addendum must cover every intermediate canonical difference
    # from the full review. Unchanged snapshot-only ancillary files are not
    # represented as independently reviewed packet content.
    original_zip = m._archive(bound(cert['artifact_bindings']['baseline_source_archive'], True))
    original_pdf = bound(cert['artifact_bindings']['baseline_pdf'], True).read_bytes()
    if derived:
        old_complete = _complete_snapshot_replay(
            m._archive(bound(cert['artifact_bindings']['baseline_snapshot_sources'], True)),
            original_zip, original_pdf, applied['manuscript_snapshot_sha256'], sources)
    else:
        old_complete = {**original_zip, **{row['path']: sources[row['path']] for row in extras}}
        m._require(m._snapshot(old_complete, original_pdf) == applied['manuscript_snapshot_sha256'],
                   'full-review snapshot does not reconstruct')
    import json
    delta = json.loads((packet / 'delta.json').read_text())
    template_provenance = (m._json(bound(bindings['template_provenance']))
                           if 'template_provenance' in bindings else {})
    derived_row = _derived_document_delta(old_complete, reviewed, auth, addendum, packet) if derived else None
    fixed_outputs = {derived_row['path'].removeprefix('manuscript/')} if derived else set()
    cumulative = _cumulative_manuscript_delta(
        {n: v for n, v in old_complete.items() if n not in fixed_outputs},
        {n: v for n, v in reviewed.items() if n not in fixed_outputs}, auth,
        template_provenance, addendum)
    if derived_row:
        cumulative.append(derived_row)
        cumulative.sort(key=lambda row: row['path'])
    m._require(cumulative ==
               [r for r in delta if r['path'].startswith('manuscript/')],
               'targeted packet omitted an intermediate manuscript change')
    # The supporting archive may change only metadata or the exact documentary
    # rows independently inspected in this addendum. Every other byte is fixed.
    support_path = bound(bindings['support_archive'])
    support = verify_support_archive(support_path)
    _verify_archive_sources(support, resolve_support_sources(metadata, repo_root=root), root)
    m._require(support['paper_id'] == paper_id and support['paper_version'] == _record_version(metadata)
               and m._sha(support_path) == metadata['support']['publication']['package_sha256'],
               'current supporting package mismatch')
    old_support_path = bound(cert['artifact_bindings']['baseline_support_archive'], True)
    m._require(m._sha(old_support_path) == applied['support_package_sha256'],
               'support baseline differs from original applied judgment')
    old_version = verify_support_archive(old_support_path)['paper_version']
    old_support = _support_digests(old_support_path, old_version)
    new_support = _support_digests(support_path, support['paper_version'])
    documented = [r for r in delta if r['path'].startswith('support/')]
    tex_prose = _validated_support_tex_prose_changes(auth, addendum, packet, old_complete,
        reviewed, sources, delta, old_support_path, support_path, old_version, support['paper_version'],
        old_support, new_support)
    if 'support_repackaging_authorization' in bindings:
        repack_auth = m._json(bound(bindings['support_repackaging_authorization']))
        m._require(repack_auth.get('paper_id') == paper_id
                   and repack_auth.get('target_version') == metadata['version']
                   and not documented, 'invalid or mixed repackaging review identity')
        m._timestamp(repack_auth['recorded_at'])
        _validate_code_first_repackaging(old_support, new_support, packet, repack_auth,
            addendum.get('support_repackaging', {}), m._sha(old_support_path), m._sha(support_path))
        from paper_writing.support_upload_policy import validate_upload_packages
        validate_upload_packages([support_path], repo_root=root)
    else:
        m._require(set(old_support) == set(new_support), 'support membership changed')
        used = []
        for name in sorted(old_support):
            before, after = old_support[name], new_support[name]
            if before == after:
                continue
            if Path(name).name in m._SUPPORT_METADATA:
                continue
            matching = [r for r in documented if tex_prose.get(name) == r or name == r['path'][8:]
                        or name.endswith('/' + r['path'][8:])]
            m._require(len(matching) == 1, 'unreviewed supporting science/code change: ' + name)
            row = matching[0]
            integrity_only = (row['path'] in addendum.get('support_integrity_rebinding_reviewed', [])
                              and _integrity_rebinding_from_archives(name, old_support_path,
                                  support_path, old_version, support['paper_version']))
            docstring_only = _authorized_module_docstring_delta(row, auth, addendum, packet)
            m._require((_documentary_support_path(name) or integrity_only or docstring_only
                        or tex_prose.get(name) == row)
                       and row['before_sha256'] == before
                       and row['after_sha256'] == after, 'support delta differs')
            used.append(row)
        m._require(sorted(r['path'] for r in used) == sorted(r['path'] for r in documented),
                   'reviewed support changes missing')
    target = cert['target']
    m._require(target['fingerprints'] == _review_workspace_fingerprints(paper_id, metadata, root)
               and target['source_archive_sha256'] == m._sha(verified_zip[0])
               and target['pdf_sha256'] == m._sha(pdf), 'final fingerprint changed')
    settings = load_registry_settings(root).get('quality_gate', {})
    m._require(settings.get('minimum_score', 5) == 5
               and settings.get('decision_standard') == 'cas_zone_1_journal'
               and settings.get('cas_zone_1_minimum_decision') == 'minor_revision', 'threshold changed')
    maximum, exception = revision_round_policy(paper_id, metadata, settings, root=root)
    total = applied['revision_rounds'] + 1
    m._require(cert['full_review_rounds'] == applied['revision_rounds']
               and cert['targeted_review_rounds'] == 1 and total <= maximum,
               'targeted judgment exceeds authorized total budget')
    m._timestamp(cert['closed_at'])
    m._require(cert['closed_by'] == 'Codex author-side editorial inspection'
               and cert['new_full_review'] is False and cert['new_lean_executions'] == 0
               and cert['new_scientific_experiments'] == 0, 'incorrect closeout provenance')
    build = m._json(bound(bindings['clean_build']))
    m._require(build['version'] == metadata['version'] and build['standalone_build'] is True
               and build['canonical_standalone_pdf_text_equal'] is True
               and any(r['sha256'] == target['pdf_sha256'] for r in build['files'])
               and any(r['sha256'] == target['source_archive_sha256'] for r in build['files']),
               'clean build is not bound to final delivery')
    blockers = manuscript_style_blockers(audit_manuscript_style(paper_id, root=root, require_ai_declaration=True))
    blockers += support_audit_blockers(audit_manuscript_support(paper_id, root=root))
    m._require(not blockers, 'deterministic gates failed: ' + '; '.join(blockers))
    # Prior ZIP/PDF bytes are replay-checked above but are cache artifacts, not
    # routine Git source. Their SHA bindings live in the committed certificate.
    evidence = [p for p in evidence if p.suffix != '.zip'
                and p != root / bindings['reviewed_pdf']['path']]
    return {'certificate': cert, 'evidence_paths': list(dict.fromkeys(evidence)),
            'score': baseline['scores']['overall'], 'decision': addendum['cas_zone_1_decision'],
            'rounds': total, 'maximum': maximum, 'exception': exception}


def validate_release(paper_id, metadata, root):
    pointer = metadata.get('writing_release', {}).get(FIELD)
    if pointer is None:
        return []
    root = Path(root).resolve()
    m._bound(pointer, root)
    checked = validate(paper_id, pointer['path'], metadata, root)
    cert = checked['certificate']
    release = metadata['writing_release']
    m._require(release['status'] == 'ready' and release['score'] == checked['score']
               and release['decision'] == checked['decision']
               and release['revision_rounds_completed'] == checked['rounds']
               and release['manuscript_version'] == cert['target']['version']
               and release.get('unresolved_review_blockers', []) == [], 'release changed judgment')
    m._require(all(release[k] == v for k, v in cert['target']['fingerprints'].items()),
               'release lost final fingerprint binding')
    return checked['evidence_paths']
