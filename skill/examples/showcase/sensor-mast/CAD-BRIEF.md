# Sensor mast root transition r2
- Modify the existing mast only, mm, local z up; foot z=0..6, web 16x6x100, seat z=106..110.
- Parameter ROOT_RADIUS=0.8 mm; round all four concave web/foot junction edges, leave outer profile, bolt bores, annular lands and datums unchanged.
- Rationale: nearest boss starts x=9 while web ends x=8; R0.8 preserves 0.2 mm separation from boss footprint. No countersink, extra rib or bolt relocation.
- Preserve original r1 sources and STEP by SHA256; base and sensor remain identical definitions, solved assembly remains grounded at base.
- Validation: four root edges lengths 6/16/6/16 at z6; BRep valid closed single solid; unchanged bounding box, bore/land/contact/load faces area, centroid and extent; actual fillet surfaces R0.8; assembly residuals satisfied.
- Exports: editable notebooks, scadpkg, STEP, STL (geometric exchange, not material/printing approval).
- CAE: original Al E69000 MPa, nu0.33, yield240 MPa; load [0,5,-50] N plus gravity; base fixed at z0, full planar frictional foot, two locked 300 N axial preloads. Same original stiffness/friction/allowable and strength FoS2, u<=0.3 mm, stress change<=10%, u change<=5%, balance5e-4; no hotspot exclusion.
- Full contact global and root local raw integration-point peaks each need two successive mesh comparisons. Fixed root spatial envelope includes all root transitions, not just a chosen favorable point. Keep all preload/locked/service peaks.
- Assumptions and not-assessed items of the original case persist; this is stated-model screening, never whole-product approval.
