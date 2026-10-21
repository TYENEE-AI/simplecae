import numpy as np
import pytest
from simplecae.robot import transform
from simplecae.robot_preflight import world_load,overlays


def test_force_and_position_frames_are_independent_and_SI_moments_preserved():
    t=transform([1,2,3],[0,0,np.pi/2]);kin={'frames':{'link':t}}
    row=world_load({'name':'push','link':'link','position_m':[.1,0,0],'position_frame':'link',
                    'force_n':[2,0,0],'moment_n_m':[0,0,.3],'frame':'world'},kin,[0,0,-10])
    assert np.allclose(row['point_world_m'],[1,2.1,3])
    assert row['force_world_n']==[2,0,0] and row['moment_world_n_m']==[0,0,.3]


def test_port_centroid_overlay_has_exactly_the_same_world_wrench():
    t=transform([1,2,3],[.2,.3,.4]);p=np.array([.01,.02,.03])+t[:3,3];center=p+np.array([.02,0,.01]);f=np.array([4,5,6]);m=np.array([.1,.2,.3])
    at_center=m+np.cross(p-center,f)
    transfer={'link':'link','world_from_component':t.tolist(),'ports':[{'port':'seat','world_point_m':p.tolist(),
               'world_surface_centroid_m':center.tolist(),'world_force_n':f.tolist(),
               'world_moment_n_m_at_application':m.tolist(),'moment_n_mm_about_surface_centroid':(t[:3,:3].T@at_center*1000).tolist(),'scalable':False}]}
    row=overlays({'links':{}},{'gravity_m_s2':[0,0,-10]}, {'frames':{}},{},[transfer])['wrenches'][0]
    assert np.allclose(row['point_world_m'],center)
    assert np.allclose(np.cross(row['point_world_m'],row['force_world_n'])+row['moment_world_n_m'],np.cross(p,f)+m)


def test_pad_outline_follows_link_pose_and_point_probe_world_frame():
    t=transform([1,2,3],[0,0,np.pi/2]);kin={'frames':{'link':t}}
    c={'gravity_m_s2':[0,0,-10],'loads':[{'name':'pad','link':'link','position_m':[0,0,0],'force_n':[5,0,0]}],
       'grasp':{'pad_contacts':[{'normal_load_name':'pad','center_link_m':[.1,.2,.3],'tangent_u_link':[0,1,0],'tangent_v_link':[0,0,1],'half_extents_m':[.01,.02]}]},
       'probes':[{'type':'point','name':'tip','link':'link','point_m':[.2,0,0],'direction':[0,1,0]}]}
    d=overlays({'links':{}},c,kin,{})
    assert np.allclose(d['pads'][0]['normal_on_finger_world'],[0,1,0])
    assert np.allclose(d['pads'][0]['tangent_u_world'],[-1,0,0])
    assert np.allclose(d['pads'][0]['center_world_m'],[.8,2.1,3.3])
    assert np.allclose(d['probes'][0]['point_world_m'],[1,2.2,3])
    assert d['pads'][0]['normal_force_n']==pytest.approx(5)
