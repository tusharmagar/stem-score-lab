import test from 'node:test';
import assert from 'node:assert/strict';
import {activeNotes,bisect,esc,formatTime,overlappingSources,pitchBounds,safeAsset,spanAt} from '../web/logic.js';
test('overlapping melody voices are retained, note ends exclusive',()=>{
 assert.deepEqual(activeNotes([[0,2,60,0],[1,3,40,1]],1.5).map(n=>n[2]),[60,40]);
 assert.equal(activeNotes([[0,2,60,0]],2).length,0);
});
test('lookup handles silence, empty streams and changing boundaries',()=>{
 assert.equal(bisect([],1),-1);assert.equal(spanAt([[2,3,'verse']],1),null);assert.equal(spanAt([[2,3,'verse']],3),null);
 assert.equal(spanAt([[0,2,'intro'],[2,3,'verse']],2)[2],'verse');
});
test('source overlap warning catches custom mixes and full mix',()=>{
 assert.equal(overlappingSources([{sources:['vocals']},{sources:['bass']}]),false);
 assert.equal(overlappingSources([{sources:['original']},{sources:['other']}]),true);
 assert.equal(overlappingSources([{sources:['bass','other']},{sources:['other']}]),true);
});
test('bass and very high notes are included; empties retain useful scale',()=>{
 assert.deepEqual(pitchBounds([[0,1,20,1],[1,2,100,0]]),[17,103]);assert.deepEqual(pitchBounds([]),[48,72]);
});
test('metadata cannot insert markup or turn an export into an external URL',()=>{
 assert.equal(esc('<script>"&'), '&lt;script&gt;&quot;&amp;');
 for(const s of ['../upload','https://evil.test','/etc/passwd','x\\y'])assert.equal(safeAsset(s),false);
 assert.equal(safeAsset('vocals/score.abc'),true);
});
test('millisecond time rounding carries across minute boundary',()=>assert.equal(formatTime(59.9999,true),'1:00.000'));
