"""Independent regressions for the second, cross-feature logic audit."""
import csv
import json
from pathlib import Path

from _helpers import TempCase
from _research_fixture import known_project
from test_models_entities import make_linear_data, spec_for
import contract_v2 as C
import lifecycle as L
import source_units as SU
import search_index as SI
import gaps as G
import models as M
import validation as V
import release as R


class CrossFeatureLogic(TempCase):
    def project(self):return C.Project(self.tmp)

    def indexed(self):
        p=self.project();materials=p.root/"materials";materials.mkdir()
        (materials/"a.txt").write_text("available field 7",encoding="utf-8")
        units=SU.SourceUnits(p,root=p.root);units.build(materials)
        index=SI.SearchIndex(p,units);index.build(materials)
        return p,materials,units,index

    def test_undecodable_source_is_not_recovered_with_replacement_characters(self):
        p=self.project();materials=p.root/"materials";materials.mkdir()
        (materials/"a.csv").write_bytes("姓名,金额\n张三,12\n".encode("gb18030"))
        units=SU.SourceUnits(p,root=materials);units.build(materials)
        self.assertFalse(units.units())
        self.assertTrue(p.read("recovery_receipt"))

    def test_source_json_duplicate_keys_are_not_silently_discarded(self):
        p=self.project();materials=p.root/"materials";materials.mkdir()
        (materials/"a.json").write_text('{"same":1,"same":2}',encoding="utf-8")
        units=SU.SourceUnits(p,root=materials);units.build(materials)
        self.assertFalse(units.units())

    def test_rebuild_replaces_active_source_versions_without_deleting_history(self):
        p,materials,units,index=self.indexed()
        source=materials/"a.txt";source.write_text("new content is substantially longer 12345",encoding="utf-8")
        units.build(materials)
        current=SU.SourceUnits(p,root=p.root).units()
        self.assertTrue(current)
        self.assertTrue(all(r["data"]["source_sha256"]==C.file_sha256(source) for r in current))
        self.assertGreater(len(p.read("source_unit")),len(current))

    def test_index_rebuild_from_fresh_object_uses_declared_material_root(self):
        p,materials,units,index=self.indexed()
        rebuilt=SI.SearchIndex(p,SU.SourceUnits(p,root=p.root));rebuilt.build(materials)
        result=rebuilt.search("available")
        self.assertGreater(result["hits"],0)

    def test_blocked_gap_is_still_unfinished(self):
        p,materials,units,index=self.indexed()
        gap=G.open_gap(p,target="dataset:person",requirement="needed field",status_detail="Source must be read")
        run=index.search("missing")
        G.attach_search(p,gap["id"],run["run"],conclusion="unreadable",note="Source could not yet be read; retry needed.")
        self.assertTrue(G.completeness(p)["errors"])

    def test_cache_cannot_reuse_changed_implementation(self):
        p=self.project();code=p.root/"implementation.py";code.write_text("x=1\n")
        artifact=p.root/"result.txt";artifact.write_text("1")
        rec=L.put(p,"known",artifact="result.txt",inputs={},code={"implementation.py":C.file_sha256(code)},rules={},environment={})
        self.assertTrue(L.is_valid(p,rec)["valid"])
        code.write_text("x=2\n")
        self.assertFalse(L.is_valid(p,rec)["valid"])

    def test_model_ids_cannot_collide_after_filename_sanitization(self):
        p=self.project();make_linear_data(self.tmp)
        for ident in ("same:OLS","same?OLS"):
            spec=spec_for(self.tmp);spec["id"]=ident;M.register(p,spec)
        self.assertEqual(M.load_spec(p,"same:OLS")["id"],"same:OLS")
        self.assertEqual(M.load_spec(p,"same?OLS")["id"],"same?OLS")

    def test_exact_independent_validation_preserves_large_integer_difference(self):
        p=self.project();make_linear_data(self.tmp)
        spec=spec_for(self.tmp,family="precision_test");M.register(p,spec)
        def producer(project,spec):
            return {"type":"scalar","target_parameter":"x","unit":"score points","scale":"absolute","n":40,"estimate":9007199254740993}
        # Match the declared semantics rather than guessing from a result file.
        spec["result"]["scale"]="absolute";M.register(p,spec)
        self.assertEqual(M.fit(p,"M1",runner=producer)["status"],"estimated")
        def checker(project,spec):return {"estimate":9007199254740992}
        checked=V.independent_check(p,"M1",validator=checker,fields=["estimate"],tolerance={"atol":0,"rtol":0})
        self.assertEqual(checked["status"],"failed")

    def test_all_failed_hard_checks_are_reported_as_hard_failures(self):
        p=self.project();G.open_gap(p,target="dataset:person",requirement="still needed",status_detail="unfinished")
        state=R.evaluate(p,{"datasets":[],"models":[],"claims":[]})
        self.assertIn("gaps_closed",state["hard_failed"])

    def test_explicit_encoding_recovers_actual_chinese_and_utf16_json(self):
        p=self.project();materials=p.root/"materials";materials.mkdir()
        (materials/"a.csv").write_bytes("姓名,金额\n张三,12\n".encode("gb18030"))
        (materials/"b.json").write_bytes('{"值":9007199254740993}'.encode("utf-16"))
        units=SU.SourceUnits(p,root=materials,encodings={"a.csv":"gb18030"});units.build(materials)
        actual=units.units();self.assertEqual(len(actual),2)
        text="\n".join((p.root/r["data"]["representation"]).read_text(encoding="utf-8") for r in actual)
        self.assertIn("张三",text);self.assertIn("9007199254740993",text);self.assertNotIn("\ufffd",text)

    def test_source_representations_remain_available_after_same_length_edit(self):
        p,materials,units,index=self.indexed()
        first=units.units()[0];path=p.root/first["data"]["representation"];before=path.read_bytes()
        source=materials/"a.txt";source.write_text(source.read_text().replace("7","8"),encoding="utf-8")
        units.build(materials)
        self.assertEqual(path.read_bytes(),before)
        self.assertNotEqual(units.units()[0]["data"]["representation"],first["data"]["representation"])

    def test_missing_full_specification_is_never_guessed_from_partial_metadata(self):
        p=self.project();make_linear_data(self.tmp);M.register(p,spec_for(self.tmp))
        M._spec_path(p,"M1").unlink()
        with self.assertRaises(M.ModelError):M.load_spec(p,"M1")

    def test_new_search_can_supersede_old_inventory_without_erasing_history(self):
        p,materials,units,index=self.indexed()
        gap=G.open_gap(p,target="dataset:person",requirement="absent field",status_detail="known fixture range")
        first=index.search("absent")
        G.attach_search(p,gap["id"],first["run"],conclusion="not_found",note="Reopened the whole original sentence: only available field 7 is recorded.")
        G.close_unavailable(p,gap["id"],reason="Read the entire original fixture, which has no absent field.")
        (materials/"b.txt").write_text("other field 9",encoding="utf-8")
        self.assertTrue(G.completeness(p)["errors"])
        units.build(materials);index.build(materials)
        second=index.search("absent")
        G.attach_search(p,gap["id"],second["run"],conclusion="not_found",note="Read both complete fixture sentences; the added sentence records other field 9 only.")
        G.close_unavailable(p,gap["id"],reason="Both complete source contexts were reopened and no requested field is present.")
        self.assertFalse(G.completeness(p)["errors"])
        self.assertEqual(len(p.latest("data_gap",gap["id"])["data"]["searches"]),2)

    def test_cache_runtime_and_idempotent_reuse_are_checked(self):
        p=self.project();(p.root/"result.txt").write_text("known")
        rec=L.put(p,"k",artifact="result.txt",inputs={},code={},rules={},environment={})
        first=L.reuse(p,"k",run_id="same");second=L.reuse(p,"k",run_id="same")
        self.assertEqual(first["run"],second["run"]);self.assertTrue(second["idempotent"])
        altered=json.loads(json.dumps(rec));altered["data"]["runtime_environment"]["python"]="a different actual runtime"
        self.assertFalse(L.is_valid(p,altered)["valid"])

    def test_dependency_cycles_and_unknown_steps_are_rejected_before_writing(self):
        p=self.project()
        for steps in ([{"id":"A","goal":"a","depends_on":["B"]},{"id":"B","goal":"b","depends_on":["A"]}],
                      [{"id":"A","goal":"a","depends_on":["unknown"]}]):
            with self.assertRaises(ValueError):L.plan(p,steps)
            self.assertFalse(p.read("workflow_step"))

    def test_independent_numeric_scope_does_not_certify_unchecked_standard_errors(self):
        import manuscript as MS
        p=known_project(self.tmp,n=20)
        self.assertTrue(V.is_current(p,"M1",field="coefficients.treatment.estimate"))
        self.assertFalse(V.is_current(p,"M1",field="coefficients.treatment.se"))
        with self.assertRaises(MS.ManuscriptError):
            MS.resolve_trace(p,"se","0.00",{"model":"M1","field":"coefficients.treatment.se","format":".2f"})

    def test_claim_scope_cannot_hide_an_unvalidated_supporting_model(self):
        import claims as CL
        import support_review as SR
        p=known_project(self.tmp,n=20);M.fit(p,"M1")
        claim=CL.register_claim(p,claim_type="result",text="The coefficient is 0.42.",block_id="b",section="results",support=[{"kind":"result","id":"M1"}])
        source=p.root/"materials/raw.csv"
        SR.review(p,claim["id"],decision="supported",reviewer="known synthetic source recheck",note="The source has a treatment difference of 0.42; this review is not an independent model validation.",
                  reread_scopes=[{"path":str(source),"sha256":C.file_sha256(source),"locator":"all rows"}])
        gate=R.evaluate(p,{"datasets":[],"models":[],"claims":[claim["id"]],"allow_limited":True})
        self.assertIn("M1",gate["scope"]["models"])
        self.assertNotIn(gate["status"],("complete","limited"))

    def test_published_readiness_is_rechecked_and_data_phase_is_not_full_research(self):
        p=known_project(self.tmp,n=20)
        scope={"datasets":["person"],"models":["M1"],"claims":[]}
        built=R.build(p,scope)
        self.assertEqual(built["status"],"complete",built);self.assertFalse(built["project_ready"])
        self.assertEqual(R.current(p)["status"],"complete")
        source=p.root/"materials/raw.csv";source.write_bytes(source.read_bytes()+b"\n")
        current=R.current(p)
        self.assertEqual(current["historical_status"],"complete")
        self.assertNotIn(current["status"],("complete","limited"))

    def test_numeric_time_sorting_and_group_identities_do_not_use_guessed_numbers(self):
        keys,method=V._ordered_time(["1","10","2"])
        self.assertEqual(sorted(keys),[1,2,10]);self.assertEqual(method,"numeric")
        with self.assertRaises(ValueError):V._ordered_time(["01/02/2020","02/03/2020"])
        p=self.project();make_linear_data(self.tmp,n=40)
        file=p.root/"data/linear.csv"
        with file.open(encoding="utf-8",newline="") as stream:rows=list(csv.DictReader(stream))
        for i,row in enumerate(rows):row["group"]="001" if i%2 else "1"
        with file.open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        M.register(p,spec_for(self.tmp))
        outcome=V.prediction_validation(p,"M1",target="y",predictors=["x"],split="group",group="group",test_fraction=.5)
        self.assertLess(outcome["test_rmse"],1e-10)

    def test_variant_output_path_cannot_escape_and_tsv_n_is_consistent(self):
        p=self.project();make_linear_data(self.tmp)
        spec=spec_for(self.tmp);spec["id"]="../../escape::variant"
        transformed=V._prepare_variant(p,spec)
        path=(p.root/transformed["inputs"][0]["dataset"]).resolve()
        self.assertIn(p.root/"output/v2/variants",path.parents)
        self.assertFalse((p.root.parent/"escape.csv").exists())
        native=p.root/"data/linear.tsv"
        with (p.root/"data/linear.csv").open(encoding="utf-8",newline="") as stream:rows=list(csv.reader(stream))
        with native.open("w",encoding="utf-8",newline="") as stream:csv.writer(stream,delimiter="\t").writerows(rows)
        spec=spec_for(self.tmp);spec["inputs"][0].update(dataset="data/linear.tsv",sha256=C.file_sha256(native))
        M.register(p,spec);self.assertEqual(M.fit(p,"M1")["status"],"estimated")
        self.assertEqual(V.independent_ols(p,"M1")["status"],"passed")

    def test_native_statistical_input_uses_real_selected_conditions_adapter(self):
        import numpy as np
        p=self.project();make_linear_data(self.tmp);array=np.column_stack([np.arange(20),1+3*np.arange(20)])
        np.save(p.root/"samples.npy",array)
        adapter=p.root/"native.py"
        adapter.write_text('''def conditions(project,spec):
    import numpy as np
    a=np.load(project.root/"samples.npy",allow_pickle=False)
    return {"checks":[{"check":"shape_and_samples","ok":a.shape==(20,2),"detail":"twenty observations with x,y columns"}]}
def fit(project,spec):
    import numpy as np
    a=np.load(project.root/"samples.npy",allow_pickle=False)
    beta=np.linalg.lstsq(np.column_stack([np.ones(len(a)),a[:,0]]),a[:,1],rcond=None)[0]
    return {"type":"scalar","target_parameter":"x","unit":"score points","scale":"absolute","n":len(a),"estimate":float(beta[1])}
''',encoding="utf-8")
        spec=spec_for(self.tmp,family="native_array");spec["inputs"]=[{"role":"fit","dataset":"samples.npy","sha256":C.file_sha256(p.root/"samples.npy"),"keys":["sample"]}]
        spec["result"]["scale"]="absolute";spec.update(conditions_runner=str(adapter)+":conditions",runner=str(adapter)+":fit")
        M.register(p,spec);self.assertTrue(M.conditions(p,"M1")["ok"])
        fitted=M.fit(p,"M1");self.assertEqual(fitted["status"],"estimated",fitted);self.assertAlmostEqual(fitted["estimate"],3)

    def test_repeated_fields_in_distinct_sources_and_reviewed_dispositions_survive(self):
        import discovery as D
        p=self.project();materials=p.root/"materials";materials.mkdir()
        for name,value in (("a.csv",7),("b.csv",9)):
            (materials/name).write_text(f"id,amount\n001,{value}\n",encoding="utf-8")
        units=SU.SourceUnits(p,root=p.root);units.build(materials);discovery=D.Discovery(p,units)
        discovery.from_materials();candidates={r["id"]:r for r in p.read("discovery_candidate")}
        amounts=[r for r in candidates.values() if r["data"]["name"]=="amount"]
        self.assertEqual(len(amounts),2)
        first=amounts[0];discovery.dispose(first["id"],"adopted",dataset="money",reason="This source field belongs to the money dataset.")
        discovery.from_materials()
        self.assertEqual(p.latest("discovery_candidate",first["id"])["data"]["disposition"],"adopted")
        self.assertFalse(discovery.coverage_errors())
        # New source bytes require a new decision even with the same headers.
        source=materials/first["data"]["sources"][0]["source"]
        source.write_text(source.read_text().replace("7","8").replace("9","8"),encoding="utf-8")
        units.build(materials);discovery.from_materials()
        self.assertEqual(p.latest("discovery_candidate",first["id"])["data"]["disposition"],"candidate")

    def test_coverage_is_per_unit_and_updated_discovery_really_runs(self):
        import discovery as D
        p,materials,units,index=self.indexed();discovery=D.Discovery(p,units)
        discovery.from_materials();self.assertFalse(discovery.coverage_errors())
        # An older discovery implementation cannot certify current discovery.
        old=p.latest("structure_coverage");producer=dict(old["producer"]);producer["code_sha256"]="0"*64
        p.append("structure_coverage",C.make_record("structure_coverage",old["id"],old["data"],producer=producer,status=old["status"],revision=old["revision"]+1),enforce_transition=False)
        self.assertTrue(discovery.coverage_errors());discovery.from_materials();self.assertFalse(discovery.coverage_errors())
        # A second logical unit within the SAME file is not covered by the first.
        original=units.units()[0]["data"];payload=dict(original);payload["locator"]={"type":"text","start":1,"end":4}
        units.upsert(payload)
        self.assertTrue(any(e["check"]=="structure_unaccounted" for e in discovery.coverage_errors()))

    def test_failed_recovery_never_reactivates_old_success_and_keeps_attempt_revisions(self):
        p,materials,units,index=self.indexed();source=materials/"a.txt"
        source.write_bytes(b"\xffbad text");units.build(materials)
        self.assertFalse(units.units());first=p.latest("recovery_receipt")
        self.assertEqual(first["data"]["failure_class"],"language_unsupported")
        source.write_bytes(b"\xffdifferent bad text");units.build(materials)
        second=p.latest("recovery_receipt")
        self.assertGreater(second["revision"],first["revision"])
        self.assertNotEqual(second["data"]["source_sha256"],first["data"]["source_sha256"])
        self.assertEqual(SU.failure_class(PermissionError("denied")),"permission")
        self.assertEqual(SU.failure_class(ModuleNotFoundError("missing")),"engine_missing")

    def test_release_assessment_is_read_only_and_detects_mid_check_evidence_changes(self):
        from unittest.mock import patch
        p=known_project(self.tmp,n=20);scope={"datasets":["person"],"models":["M1"],"claims":[]}
        def files():return {str(f.relative_to(p.root)):C.file_sha256(f) for f in p.root.rglob("*") if f.is_file()}
        before=files();self.assertEqual(R.evaluate(p,scope)["status"],"complete");self.assertEqual(files(),before)
        real=R._evaluate
        def changing(project,scope):
            outcome=real(project,scope)
            source=project.root/"materials/raw.csv";source.write_bytes(source.read_bytes()+b"\n")
            return outcome
        with patch.object(R,"_evaluate",side_effect=changing):outcome=R.evaluate(p,scope)
        self.assertEqual(outcome["status"],"failed");self.assertIn("evidence_changed_during_evaluation",outcome["hard_failed"])

    def test_publication_must_be_rebuilt_even_after_a_new_valid_fit(self):
        p=known_project(self.tmp,n=20);scope={"datasets":["person"],"models":["M1"],"claims":[]}
        self.assertEqual(R.build(p,scope)["status"],"complete")
        import designcheck as DC
        M.fit(p,"M1");V.independent_ols(p,"M1");DC.record_linkage(p,M.load_spec(p,"M1")["data"])
        self.assertEqual(R.evaluate(p,scope)["status"],"complete")
        self.assertEqual(R.current(p)["status"],"not_ready")
        self.assertEqual(R.build(p,scope)["status"],"complete")
        self.assertEqual(R.current(p)["status"],"complete")

    def test_json_pointer_preserves_parameter_punctuation_and_array_locations(self):
        data={"coefficients":{"x.dot/ratio~":{"estimate":7}},"values":[8,9]}
        pointer=C.field_pointer("coefficients","x.dot/ratio~","estimate")
        self.assertEqual(C.field_value(data,pointer),7);self.assertEqual(C.field_value(data,"/values/1"),9)
        with self.assertRaises(ValueError):C.field_parts("/bad~2escape")

    def test_native_executor_preserves_raw_logs_and_rejects_duplicate_or_nonfinite_results(self):
        import base64
        import execution as EX
        import sys
        p=self.project();make_linear_data(self.tmp);adapter=p.root/"command.py"
        spec=spec_for(self.tmp);spec["executor"]={"command":[sys.executable,str(adapter)],"code":["command.py"],"result":"native.json"}
        adapter.write_text('import sys\nfrom pathlib import Path\nsys.stdout.buffer.write(bytes([255,254,65]))\nPath("native.json").write_text(\'{"n":40,"estimate":3}\')\n',encoding="utf-8")
        result,receipt=EX.run_adapter(p,spec)
        self.assertEqual(base64.b64decode(receipt["raw_logs"]["stdout"]["base64"]),b"\xff\xfeA")
        self.assertEqual(result["estimate"],3)
        for raw in ('{"n":40,"n":41}','{"n":40,"estimate":NaN}'):
            adapter.write_text("from pathlib import Path\nPath('native.json').write_text("+repr(raw)+")\n",encoding="utf-8")
            with self.assertRaises((ValueError,EX.ExecutionError)):EX.run_adapter(p,spec)

    def test_coefficient_validation_cannot_certify_unchecked_p_value_family(self):
        p=known_project(self.tmp,n=20)
        correction=V.multiple_comparisons(p,"known",tests=[{"model":"M1","parameter":"treatment"}],rationale="Known single-test fixture")
        self.assertEqual(correction["status"],"unassessed")
        self.assertIsNone(correction["tests"][0]["p_raw"])

    def test_builtin_model_does_not_relabel_raw_beta_as_odds_ratio(self):
        p=self.project();make_linear_data(self.tmp);spec=spec_for(self.tmp)
        spec["result"]["scale"]="odds_ratio";M.register(p,spec)
        result=M.fit(p,"M1");self.assertNotEqual(result["status"],"estimated")

    def test_presentation_native_text_table_notes_and_visual_gap_are_preserved(self):
        import zipfile
        p=self.project();materials=p.root/"materials";materials.mkdir()
        ns='xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        slide=f'<root {ns}><a:p><a:r><a:t>原始金额 19 元</a:t></a:r></a:p><a:tbl><a:tr><a:tc><a:p><a:r><a:t>金额</a:t></a:r></a:p></a:tc></a:tr></a:tbl></root>'
        note=f'<root {ns}><a:p><a:r><a:t>附注：合成资料</a:t></a:r></a:p></root>'
        with zipfile.ZipFile(materials/"test.pptx","w") as z:
            z.writestr("ppt/slides/slide1.xml",slide);z.writestr("ppt/notesSlides/notesSlide1.xml",note)
        units=SU.SourceUnits(p,root=p.root);units.build(materials);active=units.units()
        texts=[(p.root/r["data"]["representation"]).read_text(encoding="utf-8") for r in active]
        self.assertTrue(any("原始金额 19 元" in text for text in texts));self.assertTrue(any("附注：合成资料" in text for text in texts))
        self.assertEqual(len([r for r in active if r["data"]["unit_type"]=="table"]),1)
        self.assertTrue(any(r["data"]["unrecovered"] for r in active))

    def test_included_material_with_unrecovered_scope_cannot_pass_source_gate(self):
        import evidence as E
        import discovery as D
        p=known_project(self.tmp,n=6);units=SU.SourceUnits(p,root=p.root)
        payload=dict(units.units()[0]["data"]);payload["unrecovered"]=["footer amounts not yet read"]
        units.upsert(payload);D.Discovery(p,units).from_materials()
        from _research_fixture import final_review
        final_review(p.root)
        with self.assertRaisesRegex(ValueError,"unresolved recovery scope"):
            E.source_coverage(p,E.final_review(p)[0])
        report=p.root/"scope-review.md"
        with (p.root/"materials/raw.csv").open(encoding="utf-8",newline="") as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),6)
        report.write_text("Synthetic fault control: reopened the complete original CSV, including all rows and the end of file. It has id, treatment, y; there is no footer. The injected footer gap is resolved by this complete reread.",encoding="utf-8")
        units.review_scope(units.units()[0]["id"],report=report,reviewer="synthetic original rereader",note="All six rows and end of file reopened; no footer exists.",remaining=[])
        D.Discovery(p,units).from_materials();final_review(p.root)
        self.assertTrue(E.source_coverage(p,E.final_review(p)[0]))
        report.write_text("changed review",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"review report is missing or changed"):E.source_coverage(p,E.final_review(p)[0])

    def test_repeated_same_name_fields_within_one_source_keep_each_occurrence(self):
        import discovery as D
        p=self.project();materials=p.root/"materials";materials.mkdir()
        (materials/"records.txt").write_text("amount: 7\namount: 9\n",encoding="utf-8")
        units=SU.SourceUnits(p,root=p.root);units.build(materials);discovery=D.Discovery(p,units);discovery.from_materials()
        amounts=[r for r in discovery._active_candidates().values() if r["data"]["name"]=="amount"]
        self.assertEqual(len(amounts),2)

    def test_changed_representation_cannot_support_discovery_or_not_found_search(self):
        import discovery as D
        p,materials,units,index=self.indexed();unit=units.units()[0]
        rep=units.representation_path(unit);rep.write_text("lost every field",encoding="utf-8")
        with self.assertRaises(C.IntegrityError):D.Discovery(p,units).from_materials()
        self.assertTrue(index.stale()["stale"])
        with self.assertRaises(SystemExit):index.search("available")
        with self.assertRaises(C.IntegrityError):index.build(materials)
        # Recovery from the unchanged original restores the real representation.
        units.build(materials);index.build(materials);self.assertEqual(index.search("available")["hits"],1)
        # A legitimate new recovery revision also invalidates the prior index,
        # even when the original bytes never changed.
        data=dict(units.units()[0]["data"]);name,digest=units.write_rep(unit["id"],"available field 7\n")
        data.update(representation=name,representation_sha256=digest);units.upsert(data)
        self.assertTrue(index.stale()["stale"])

    def test_reference_access_rejects_lossy_decoding_instead_of_claiming_readable_text(self):
        import refs
        p=self.project();path=p.root/"article.txt";path.write_bytes(b"A genuine sentence about the result.\xff")
        refs.register(p,"R1",authors="Synthetic author",title="Synthetic reading fixture",year="2026",venue="Software test")
        with self.assertRaises(UnicodeError):refs.verify_access(p,"R1",text_path="article.txt",level="abstract")
        self.assertEqual(p.latest("reference","R1")["data"]["access"]["level"],"metadata")

    def test_failed_independent_comparison_still_discloses_shared_preprocessing(self):
        p=self.project();make_linear_data(self.tmp)
        spec=spec_for(self.tmp);M.register(p,spec)
        def deliberately_wrong(project,spec):
            return {"type":"coefficient_table","target_parameter":"x","unit":"score points","scale":"linear","n":40,
                    "estimate":4,"coefficients":{"const":{"estimate":2},"x":{"estimate":4}}}
        self.assertEqual(M.fit(p,"M1",runner=deliberately_wrong)["status"],"estimated")
        checked=V.independent_ols(p,"M1",shared_preprocessing=True)
        self.assertEqual(checked["status"],"failed")
        recorded=p.latest("validation_result")["data"]
        self.assertEqual(recorded["independent"]["shared"],["extraction","transform"])
