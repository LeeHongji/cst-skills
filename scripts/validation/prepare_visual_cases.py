"""Public pure verification helpers; historical drivers and data are excluded."""
from cst_cad.dsl import ModelBuilder

def primitives():
    m=ModelBuilder(model_id='cad-asymmetric-dimension-standard',title='非对称尺寸基准 / Asymmetric dimension standard')
    m.units(length='mm',frequency='GHz');m.material('Dielectric',epsilon=2.2);m.material('PEC',kind='pec')
    m.layer('base',-2,0,'Dielectric',role='substrate');m.layer('metal',0,2,'PEC')
    m.net('BASE','base',net_class='reference',color=(80,126,122)).box(-10,-6,14,10)
    # A non-convex L: 12*3 + 3*7 = 57 mm², extruded 2 mm => 114 mm³.
    m.net('L_PROFILE','metal',color=(224,179,107)).polygon([(-6,-3),(6,-3),(6,0),(-3,0),(-3,7),(-6,7)],solid_id='l_profile')
    m.rule('containment','board_containment','layer:metal',reference_net='BASE')
    m.rule('connected','net_connectivity','*',max_components=1)
    return m.build()

def multilayer():
    m=ModelBuilder(model_id='cad-multilayer-hairpin',title='多层回折与遮挡 / Multilayer hairpin and occlusion')
    m.units(length='mm',frequency='GHz');m.material('Board',epsilon=3.55);m.material('Metal',kind='pec')
    m.layer('base',-1,0,'Board',role='substrate');m.layer('lower',0,.3,'Metal');m.layer('upper',3,3.3,'Metal')
    m.net('BOARD','base',net_class='reference',color=(80,126,122)).box(-12,-10,12,10)
    # Open U, a long slot that must remain open under real tessellation.
    m.net('LOWER_U','lower',color=(224,179,107)).polygon([(-8,7),(-8,-7),(8,-7),(8,7),(6,7),(6,-5),(-6,-5),(-6,7)],solid_id='hairpin')
    m.net('UPPER_CROSSING','upper',color=(181,173,229)).box(-10,-1,10,1)
    m.rule('connected','net_connectivity','*',max_components=1)
    return m.build()

def failed_spacing():
    m=ModelBuilder(model_id='cad-drc-negative-spacing',title='间距失败定位 / Deliberate spacing failure')
    m.units(length='mm',frequency='GHz');m.material('PEC',kind='pec');m.layer('top',0,1,'PEC')
    m.net('LEFT','top',color=(224,179,107)).box(-5,-5,0,5)
    m.net('RIGHT','top',color=(181,173,229)).box(.1,-5,5,5)
    m.rule('min_gap','min_spacing','layer:top',min_spacing=.5)
    return m.build()
