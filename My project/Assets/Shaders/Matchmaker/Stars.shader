// The night sky behind the globe: tiny quads, coloured per vertex, each twinkling on its
// own phase (stored in the vertex colour's alpha).
Shader "Matchmaker/Stars"
{
    Properties { _Twinkle ("Twinkle", Float) = 0.45 }
    SubShader
    {
        Tags { "RenderType"="Transparent" "Queue"="Transparent-10" "RenderPipeline"="UniversalPipeline" }
        Pass
        {
            Name "Stars"
            Tags { "LightMode"="UniversalForward" }
            Blend One One
            ZWrite Off
            Cull Off
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float _Twinkle;
            CBUFFER_END

            struct Attributes { float4 positionOS : POSITION; float4 color : COLOR; float2 uv : TEXCOORD0; };
            struct Varyings { float4 positionCS : SV_POSITION; float4 color : COLOR; float2 uv : TEXCOORD0; };

            Varyings vert(Attributes i)
            {
                Varyings o;
                o.positionCS = TransformObjectToHClip(i.positionOS.xyz);
                o.color = i.color;
                o.uv = i.uv;
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                // A soft round point inside each quad.
                float d = length(i.uv * 2.0 - 1.0);
                float shape = saturate(1.0 - d);
                shape *= shape;
                float phase = i.color.a * 6.2831;
                float tw = 1.0 - _Twinkle + _Twinkle * (0.5 + 0.5 * sin(_Time.y * (1.3 + i.color.a * 2.0) + phase));
                return half4(i.color.rgb * shape * tw, 1.0);
            }
            ENDHLSL
        }
    }
}
